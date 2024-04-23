import logging
import asyncio
import json
import os
import time

import cv2
import openpyxl
from openpyxl.drawing.image import Image as ExcelImage

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from libcolonyfind.colony_finder import ColonyFinder
from libmotorctrl import DriveManager, DriveTarget


@dataclass
class Well:
    id: str
    x: int
    y: int
    has_sample: bool


@dataclass
class Colony:
    id: int
    x: float
    y: float
    sample_duration: timedelta
    well: str


@dataclass
class PetriDish:
    id: int
    name: str
    x: int
    y: int
    raw_image_path: str
    annotated_image_path: str
    colonies: list[Colony] = field(default_factory=list)


with open(Path(__file__).parent / "baseplate_locations.json", encoding="utf8") as f:
    CONFIG_LOCATIONS = json.load(f)

with open(Path(__file__).parent / "runtime_parameters.json", encoding="utf8") as f:
    CONFIG_PARAMETERS = json.load(f)


class ProcessControlWorker(QObject):
    finished = pyqtSignal()  # Indicates that thread can be terminated
    exception = pyqtSignal(str)  # Indicates something went wrong; thread terminated
    colony_count = pyqtSignal(int)  # Indicates maximum progress bar value
    colony_index = pyqtSignal(int)  # Indicates progress bar value
    status_msg = pyqtSignal(str)  # Indicates status message displayed to user
    state = pyqtSignal(str)  # Indicates to main process where in execution flow we are

    def __init__(
        self,
        petri_dish_names,
        petri_dish_count,
        sterilizer_dwell_duration,
        cooling_duration,
        parent=None,
    ):
        QThread.__init__(self, parent)
        self.main_thread = QThread.currentThread()

        self.paused = False

        self.petri_dishes = []
        for petri_dish_index in range(petri_dish_count):
            petri_dish = CONFIG_LOCATIONS["petri_dishes"][petri_dish_index]
            self.petri_dishes.append(
                PetriDish(
                    id=petri_dish["id"],
                    name=petri_dish_names[petri_dish["id"] - 1],
                    x=petri_dish["x"],
                    y=petri_dish["y"],
                    raw_image_path="",
                    annotated_image_path="",
                    colonies=[],
                )
            )

        self.wells = []
        for well in CONFIG_LOCATIONS["wells"]:
            self.wells.append(
                Well(id=well["id"], x=well["x"], y=well["y"], has_sample=False)
            )

        self.sterilizer_dwell_duration = sterilizer_dwell_duration
        self.cooling_duration = cooling_duration

        self.run_id = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        self.output_dir = Path("output") / self.run_id
        self.output_dir.mkdir(parents=True)
        logging.info("Output path set to %s", self.output_dir)
        self.logfile = self.output_dir / "process.log"  # TODO Gzip this
        logging.basicConfig(
            filename=self.logfile,
            filemode="a",
            format="%(asctime)s,%(msecs)d %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
            force=True,
            level=logging.INFO,
        )
        # Also log to console
        console = logging.StreamHandler()
        logging.getLogger("").addHandler(console)

    def run_full_proc(self):
        try:
            process_actions = [
                ("CAM_INIT", self.init_camera, ()),
                ("DRIVE_INIT", self.init_drives, ()),
                ("DRIVE_HOME", self.home_drives, ()),
                ("IMG_CAP", self.capture_images, ()),
                ("IMG_PROC", self.locate_valid_colonies, ()),
                ("SAMP_CYC", self.run_sampling_cycle, ()),
                ("SAV_TAB", self.save_tabulated_data, ()),
                ("TERM", self.terminate, {"polite": True}),
            ]

            for state_label, method, args in process_actions:
                if hasattr(self, "drive_ctrl"):
                    if self.drive_ctrl.abort:
                        break
                self.state.emit(state_label)
                # Parse positional arguments
                if isinstance(args, dict):
                    method(**args)
                else:
                    method(*args)

            if not self.drive_ctrl.abort:
                self.state.emit("DONE")
            else:
                self.status_msg.emit("Run aborted by user!")
        except Exception as e:
            try:
                logging.error("Encountered error, trying to save data...")
                self.save_tabulated_data()
                self.terminate(polite=False)
                time.sleep(0.2)  # HACK Ensure Excel file is saved
            finally:
                logging.error(e)
                self.exception.emit(str(e))
                self.moveToThread(self.main_thread)
        else:
            self.moveToThread(self.main_thread)
            self.finished.emit()

    def init_drives(self):
        self.status_msg.emit("Initializing drives...")
        self.drive_ctrl = DriveManager()
        asyncio.run(self.drive_ctrl.init_drives())

    def init_camera(self):
        self.status_msg.emit("Initializing camera...")
        # Configure the camera for maximum resolution, very low exposure
        self.cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 3264)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 2448)
        self.cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.05)

        self.raw_image_path = self.output_dir / "01_raw_images"
        self.raw_image_path.mkdir()
        logging.info("Camera initialized")

    def home_drives(self):
        try:
            self.status_msg.emit("Homing drive Z [1/3]...")
            asyncio.run(self.drive_ctrl.home(DriveTarget.DriveZ))
            self.status_msg.emit("Homing drive X [2/3]...")
            asyncio.run(self.drive_ctrl.home(DriveTarget.DriveX))  # TODO Parallelize
            self.status_msg.emit("Homing drive Y [3/3]...")
            asyncio.run(self.drive_ctrl.home(DriveTarget.DriveY))
        except Exception as e:
            self.exception.emit(str(e))

    def capture_images(self):
        logging.info("Capturing images...")
        image_count = 0
        # TODO Raise z-axis first
        # If we aren't already at maximum z, the needle will crash
        for petri_dish in self.petri_dishes:
            image_count += 1
            self.status_msg.emit(
                f"Capturing image of Petri dish {petri_dish.name} [{image_count}/{len(self.petri_dishes)}]..."
            )
            asyncio.run(
                self.drive_ctrl.move_direct(
                    int(
                        (petri_dish.x + CONFIG_PARAMETERS["camera_offset"]["x"])
                        * 10**3
                    ),
                    int(
                        (petri_dish.y + CONFIG_PARAMETERS["camera_offset"]["y"])
                        * 10**3
                    ),
                    int(50 * 10**3),
                )
            )
            if self.drive_ctrl.abort:
                break
            # HACK We call `cam.read()` unnecessarily
            # It is necessary to call `cam.read()` (discarding the result), and
            # then call `cam.read()` to get the correct image.
            result = False
            while not result:  # Possibly unnecessary
                result, _ = self.cam.read()
            result, image = self.cam.read()
            if not result:
                logging.critical("Failed to capture Petri dish image!")
                raise Exception(
                    f"Invalid image capture result for Petri dish {petri_dish.id}: {petri_dish.name}!"
                )

            petri_dish.raw_image_path = Path(
                self.raw_image_path / f"{petri_dish.name}.jpg"
            )
            cv2.imwrite(str(petri_dish.raw_image_path), image)
            logging.info("Saved raw image for petri dish %s", petri_dish.name)

        self.cam.release()

    def locate_valid_colonies(self):
        self.status_msg.emit("Processing images...")
        self.csv_out_dir = self.output_dir / "02_csv_data"
        self.annotated_image_dir = self.output_dir / "03_annotated"
        self.csv_out_dir.mkdir()
        self.annotated_image_dir.mkdir()

        colony_finder = ColonyFinder(self.raw_image_path, self.csv_out_dir)
        colony_finder.run_full_proc()
        raw_baseplate_coords_dict = colony_finder.get_coords()
        annotated_images = colony_finder.annotate_images()
        for petri_dish in self.petri_dishes:
            petri_dish.annotated_image_path = (
                self.annotated_image_dir / f"{petri_dish.name}.jpg"
            )
            cv2.imwrite(
                str(petri_dish.annotated_image_path),
                annotated_images[petri_dish.name],
            )

        colony_count = 0
        for petri_dish in self.petri_dishes:
            if petri_dish.name in raw_baseplate_coords_dict:
                for colony in raw_baseplate_coords_dict[petri_dish.name]:
                    petri_dish.colonies.append(
                        Colony(
                            id=colony_count,
                            x=(petri_dish.x + colony[0]),
                            y=(petri_dish.y + colony[1]),
                            sample_duration=None,
                            well=None,
                        )
                    )
                    colony_count += 1
                if (
                    colony_count >= 96
                ):  # Sanity check if too many colonies returned by libcolonyfind
                    break
            if colony_count >= 96:
                break
        self.total_colonies = colony_count
        self.colony_count.emit(self.total_colonies)

    def run_sampling_cycle(self):
        self.sterilize_needle()

        for petri_dish in self.petri_dishes:
            for colony in petri_dish.colonies:
                logging.info("Sampling from colony %s...", colony.id)
                start_time = datetime.now()
                self.colony_index.emit(colony.id)
                self.status_msg.emit(f"Sampling colony {colony.id + 1}...")
                asyncio.run(
                    self.drive_ctrl.move(
                        int(colony.x * 10**3),
                        int(colony.y * 10**3),
                        int(CONFIG_PARAMETERS["colony_depth"] * 10**3),
                    )
                )
                if self.drive_ctrl.abort:
                    break

                self.status_msg.emit(f"Depositing colony {colony.id + 1}...")
                target_well = self.wells[colony.id]
                colony.well = target_well.id
                logging.info("Moving to target well %s...", target_well.id)
                asyncio.run(
                    self.drive_ctrl.move(
                        int(target_well.x * 10**3),
                        int(target_well.y * 10**3),
                        int(CONFIG_PARAMETERS["well_depth"] * 10**3),
                    )
                )
                if self.drive_ctrl.abort:
                    break
                self.sterilize_needle()
                if self.drive_ctrl.abort:
                    break
                colony.sample_duration = datetime.now() - start_time

                if self.drive_ctrl.abort:
                    break
            if self.drive_ctrl.abort:
                break

    def sterilize_needle(self):
        self.status_msg.emit("Sterilizing needle...")

        asyncio.run(
            self.drive_ctrl.move(
                int(CONFIG_LOCATIONS["sterilizer"]["x"] * 10**3),
                int(CONFIG_LOCATIONS["sterilizer"]["y"] * 10**3),
                int(CONFIG_LOCATIONS["sterilizer"]["z"] * 10**3),
            )
        )
        logging.info("Sleeping for %s seconds...", self.sterilizer_dwell_duration)
        time.sleep(self.sterilizer_dwell_duration)

        asyncio.run(
            self.drive_ctrl.move(
                int(CONFIG_LOCATIONS["sterilizer"]["x"] * 10**3),
                int(CONFIG_LOCATIONS["sterilizer"]["y"] * 10**3),
                int(CONFIG_PARAMETERS["cruise_depth"] * 10**3),
            )
        )
        logging.info("Sleeping for %s seconds...", self.cooling_duration)
        time.sleep(self.cooling_duration)

    def pause(self):
        logging.info("Pausing drives...")
        self.paused = True
        asyncio.run(self.drive_ctrl.stop())

    def resume(self):
        logging.info("Resuming drives...")
        self.paused = False
        asyncio.run(self.drive_ctrl.resume())

    def save_tabulated_data(self):
        self.status_msg.emit("Saving run data...")
        workbook = openpyxl.Workbook()
        for petri_dish in self.petri_dishes:
            if petri_dish.id == 1:
                active_worksheet = workbook.active
                active_worksheet.title = petri_dish.name
            else:
                active_worksheet = workbook.create_sheet(petri_dish.name)
            active_worksheet.append(
                ["Well", "Origin X", "Origin Y", "Cycle Duration (s)"]
            )
            for row_num, colony in enumerate(petri_dish.colonies):
                if colony.sample_duration is not None:
                    active_worksheet.append(
                        [
                            colony.well,
                            colony.x,
                            colony.y,
                            colony.sample_duration.total_seconds(),
                        ]
                    )
                img = ExcelImage(petri_dish.raw_image_path)  # TODO Crop before insert
                active_worksheet.add_image(img, f"F{row_num + 2}")
        workbook.save(self.output_dir / f"run-data-{self.run_id}.xlsx")

    def terminate(self, polite=False):
        logging.info("Terminating process control...")
        if polite:
            self.colony_index.emit(self.total_colonies)
            self.status_msg.emit("Terminating process control...")
        self.cam.release()
        if polite:
            logging.info("Returning home...")
            asyncio.run(self.drive_ctrl.move(450_000, -90_000, 0))
        asyncio.run(self.drive_ctrl.terminate())
        logging.info("Process control terminated")
        if polite:
            self.status_msg.emit("Process control terminated!")
