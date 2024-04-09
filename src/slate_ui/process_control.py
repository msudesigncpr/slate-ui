import logging
import asyncio
import json
import random
import time

import cv2

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from libcolonyfind import find_colonies
from libmotorctrl import DriveManager, DriveTarget


@dataclass
class Colony:
    id: int
    x: float
    y: float
    is_target: bool


@dataclass
class PetriDish:
    id: int
    name: str
    x: int
    y: int
    is_target: bool
    raw_image: str
    colonies: list[Colony] = field(default_factory=list)


@dataclass
class Well:
    id: int
    x: int
    y: int
    has_sample: bool


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
        self, petri_dish_count, sterilizer_dwell_duration, cooling_duration, parent=None
    ):
        QThread.__init__(self, parent)

        self.main_thread = QThread.currentThread()

        self.petri_dishes = []
        for petri_dish in CONFIG_LOCATIONS["petri_dishes"]:
            self.petri_dishes.append(
                PetriDish(
                    id=petri_dish["id"],
                    name=f"P{petri_dish['id']}",
                    x=petri_dish["x"],
                    y=petri_dish["y"],
                    is_target=False,
                    raw_image="",
                    colonies=[],
                )
            )

        self.wells = []
        for well in CONFIG_LOCATIONS["wells"]:
            self.wells.append(
                Well(id=well["id"], x=well["x"], y=well["y"], has_sample=False)
            )

        self.set_petri_dish_count(petri_dish_count)
        self.sterilizer_dwell_duration = sterilizer_dwell_duration
        self.cooling_duration = cooling_duration

        self.output_dir = Path("output") / datetime.now().strftime("%Y%m%dT%H%M%SZ")
        self.output_dir.mkdir(parents=True)
        logging.info("Output path set to %s", self.output_dir)
        self.logfile = Path(self.output_dir / "process.log")  # TODO Gzip this
        logging.basicConfig(
            filename=self.logfile,
            filemode="a",
            format="%(asctime)s,%(msecs)d %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
            force=True,
            level=logging.INFO,
        )

    def run_full_proc(self, petri_dish_count=4):
        try:
            self.state.emit("CAM_INIT")
            self.init_camera()
            self.state.emit("DRIVE_INIT")
            self.init_drives()
            self.state.emit("DRIVE_HOME")
            self.home_drives()
            self.state.emit("IMG_CAP")
            self.capture_images()
            self.state.emit("IMG_PROC")
            self.locate_valid_colonies()
            self.state.emit("SAMP_CYC")
            self.run_sampling_cycle()
            self.state.emit("TERM")
            self.terminate(polite=True)
            self.state.emit("DONE")
        except Exception as e:
            self.moveToThread(self.main_thread)
            self.exception.emit(str(e))
            logging.error(e)
        else:
            self.moveToThread(self.main_thread)
            self.finished.emit()

    def set_petri_dish_count(self, petri_dish_count):
        self.petri_dish_count = petri_dish_count
        for i in range(petri_dish_count):
            self.petri_dishes[i].is_target = True

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

        self.raw_image_path = Path(self.output_dir / "01_raw_images")
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
            if petri_dish.is_target:
                image_count += 1
                self.status_msg.emit(
                    f"Capturing image of Petri dish {petri_dish.id} [{image_count}/{self.petri_dish_count}]..."
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
                    break  # TODO Test this
                # HACK We call `cam.read()` unnecessarily
                # It is necessary to call `cam.read()` (discarding the result), and
                # then call `cam.read()` to get the correct image.
                self.cam.read()
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
        self.cam.release()

    def locate_valid_colonies(self):
        self.status_msg.emit("Processing images...")
        self.csv_out_dir = Path(self.output_dir / "02_csv_data")
        self.annotated_image_dir = Path(self.output_dir / "03_annotated")
        self.csv_out_dir.mkdir()
        self.annotated_image_dir.mkdir()
        raw_baseplate_coords_dict = find_colonies(
            self.raw_image_path, self.csv_out_dir, self.annotated_image_dir
        )  # TODO Clean up the data structures!
        colony_counter = 0
        for petri_dish in self.petri_dishes:
            if petri_dish.name in raw_baseplate_coords_dict:
                for colony in raw_baseplate_coords_dict[petri_dish.name]:
                    petri_dish.colonies.append(
                        Colony(
                            id=colony_counter,
                            x=(petri_dish.x + colony[0]),
                            y=(petri_dish.y + colony[1]),
                            is_target=True,
                        )
                    )
                    colony_counter += 1
        self.colony_count.emit(colony_counter)

    def run_sampling_cycle(self):
        self.sterilize_needle()

        for petri_dish in self.petri_dishes:
            if petri_dish.is_target:
                for colony in petri_dish.colonies:
                    if colony.x > 38.34:  # TODO Remove this line
                        logging.info("Sampling from colony %s...", colony.id)
                        self.colony_index.emit(colony.id)
                        self.status_msg.emit(f"Sampling colony {colony.id + 1}...")
                        asyncio.run(
                            self.drive_ctrl.move(
                                int(colony.x * 10**3),
                                int(colony.y * 10**3),
                                int(CONFIG_PARAMETERS["colony_depth"] * 10**3),
                            )
                        )

                        self.status_msg.emit(f"Depositing colony {colony.id}...")
                        target_well = self.wells[colony.id]
                        logging.info("Moving to target well %s...", target_well.id)
                        asyncio.run(
                            self.drive_ctrl.move(
                                int(target_well.x * 10**3),
                                int(target_well.y * 10**3),
                                int(CONFIG_PARAMETERS["well_depth"] * 10**3),
                            )
                        )
                        self.sterilize_needle()

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

    async def pause(self):
        logging.info("Pausing drives...")
        await self.drive_ctrl.stop()

    async def resume(self):
        logging.info("Resuming drives...")
        await self.drive_ctrl.resume()
        # TODO We need to resume last movement command

    def terminate(self, polite=False):
        if polite:
            self.status_msg.emit("Terminating process control...")
        self.cam.release()
        if polite:
            asyncio.run(self.drive_ctrl.move(450_000, -90_000, 0))
        asyncio.run(self.drive_ctrl.terminate())
        if polite:
            self.status_msg.emit("Process control terminated!")
