import asyncio
import cv2
import json
import logging
import random
import sys

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


class ProcessControl:
    def __init__(self, petri_dish_count):
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

        self.metadata_dir = Path("metadata") / datetime.isoformat(datetime.today())
        self.metadata_dir.mkdir(parents=True)
        logging.info("Metadata path set to %s", self.metadata_dir)

        self.init_camera()
        logging.info("Camera initialized")

        self.work_task = asyncio.create_task(self.init_drives())

    def set_petri_dish_count(self, petri_dish_count):
        self.petri_dish_count = petri_dish_count
        for i in range(petri_dish_count):
            self.petri_dishes[i].is_target = True

    async def init_drives(self):
        self.drive_ctrl = DriveManager()
        await self.drive_ctrl.init_drives()

    def init_camera(self):
        # Configure the camera for maximum resolution, very low exposure
        self.cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, 3264)
        self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 2448)
        self.cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.05)

        self.raw_image_path = Path(self.metadata_dir / "raw_images")
        self.raw_image_path.mkdir()

    async def home_drives(self):
        await self.drive_ctrl.home(DriveTarget.DriveZ)
        async with asyncio.TaskGroup() as home_tg:
            home_tg.create_task(self.drive_ctrl.home(DriveTarget.DriveX))
            home_tg.create_task(self.drive_ctrl.home(DriveTarget.DriveY))
        logging.info("Homing complete")

    async def calibrate(self):
        print("TODO")  # TODO

    async def capture_images(self, petri_dish_count):
        logging.info("Capturing images...")
        for petri_dish in self.petri_dishes[:petri_dish_count]:
            await self.drive_ctrl.move(petri_dish.x, petri_dish.y)
            # HACK We call `cam.read()` unnecessarily
            # It is necessary to call `cam.read()` (discarding the result), and
            # then call `cam.read()` to get the correct image.
            self.cam.read()
            result, image = self.cam.read()
            if not result:
                logging.critical("Failed to capture Petri dish image!")
                raise Exception("Invalid image capture result!")

            petri_dish.raw_image_path = Path(self.raw_image_path / f"P{petri_dish.id}")
            cv2.imwrite(petri_dish.raw_image_path, image)
        self.cam.release()

    async def locate_valid_colonies(self):
        print("TODO")  # TODO

    async def extract_target_colonies(self):
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

    async def terminate(self):
        await self.work_task
        self.cam.release()
        await self.drive_ctrl.move(450_000, -90_000, 0)
        await self.drive_ctrl.terminate()
