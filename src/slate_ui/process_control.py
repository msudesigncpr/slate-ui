import logging
import asyncio
import json
import random

import cv2

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from libmotorctrl import DriveManager, DriveTarget


@dataclass
class Colony:
    id: int
    dish: int
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
    colonies: list


with open(Path(__file__).parent / "baseplate_locations.json", encoding="utf8") as f:
    CONFIG = json.load(f)


class ProcessControlWorker(QObject):
    finished = pyqtSignal()  # Indicates that thread can be terminated
    exception = pyqtSignal(str)  # Indicates something went wrong; thread terminated
    progress = pyqtSignal(int)  # Indicates progress bar value
    status_msg = pyqtSignal(str)  # Indicates status message displayed to user
    state = pyqtSignal(str)  # Indicates to main process where in execution flow we are

    def __init__(self, petri_dish_count, parent=None):
        QThread.__init__(self, parent)

        self.main_thread = QThread.currentThread()

        self.petri_dishes = []
        for petri_dish in CONFIG["petri_dishes"]:
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

        self.set_petri_dish_count(petri_dish_count)

        self.metadata_dir = Path("metadata") / datetime.now().strftime("%Y%m%dT%H%M%SZ")
        self.metadata_dir.mkdir(parents=True)
        logging.info("Metadata path set to %s", self.metadata_dir)
        self.logfile = Path(self.metadata_dir / "process.log")
        logging.basicConfig(
            filename=self.logfile,
            filemode="a",
            format="%(asctime)s,%(msecs)d %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
            force=True,
            level=logging.DEBUG,
        )

    def run_full_proc(self, petri_dish_count=4):
        try:
            self.init_camera()
            self.state.emit("CAM_INIT")
            self.init_drives()
            self.state.emit("DRIVE_INIT")
            self.home_drives()
            self.state.emit("DRIVE_HOME")
            self.capture_images()
            self.state.emit("IMG_CAP")
            self.terminate(polite=True)
            self.state.emit("DONE")
        except Exception as e:
            self.moveToThread(self.main_thread)
            self.exception.emit(str(e))
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

        self.raw_image_path = Path(self.metadata_dir / "raw_images")
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
        for petri_dish in self.petri_dishes:
            if petri_dish.is_target:
                image_count += 1
                self.status_msg.emit(
                    f"Capturing image of Petri dish {petri_dish.id} [{image_count}/{self.petri_dish_count}]..."
                )
                asyncio.run(
                    self.drive_ctrl.move_direct(
                        int((petri_dish.x + CONFIG["camera_offset"]["x"]) * 10**3),
                        int((petri_dish.y + CONFIG["camera_offset"]["y"]) * 10**3),
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

    async def locate_valid_colonies(self):
        print("TODO")  # TODO

    async def extract_target_colonies(self):
        self.status_msg.emit("Extracting target colony list...")
        total_valid_colonies = 0
        for petri_dish in self.petri_dishes:
            if petri_dish.is_target:
                total_valid_colonies += len(petri_dish.colonies)

        if total_valid_colonies <= 96:
            for petri_dish in self.petri_dishes:
                for colony in petri_dish.colonies:
                    colony.is_target = True
        else:
            for i in range(96):
                start_c = True  # HACK
                dish_colonies_valid = []
                while start_c or len(dish_colonies_valid) == 0:
                    start_c = False
                    target_petri_dish = random.randrange(self.petri_dish_count)
                    dish_colonies_all = self.petri_dishes[target_petri_dish].colonies
                    dish_colonies_valid = [
                        colony for colony in dish_colonies_all if not colony.is_target
                    ]

                target_colony = random.randrange(len(dish_colonies_valid))
                self.petri_dishes[target_petri_dish].colonies[
                    target_colony
                ].is_target = True
        logging.info("Target colonies selected")

    async def run_sampling_cycle(self):
        print("TODO")  # TODO

    async def pause(self):
        logging.info("Pausing drives...")
        await self.drive_ctrl.stop()

    async def resume(self):
        logging.info("Resuming drives...")
        await self.drive_ctrl.resume()
        # TODO We need to resume last movement command

    def terminate(self, polite=False):
        self.status_msg.emit("Terminating process control...")
        self.cam.release()
        if polite:
            asyncio.run(self.drive_ctrl.move(450_000, -90_000, 0))
        asyncio.run(self.drive_ctrl.terminate())
        self.status_msg.emit("Process control terminated!")
