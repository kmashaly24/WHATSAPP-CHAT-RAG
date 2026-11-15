from .BaseController import BaseController
from fastapi import UploadFile
from models import ResponseSignal
import os
import shutil
import logging

logger = logging.getLogger("uvicorn.error")

class ProjectController(BaseController):
    
    def __init__(self):
        super().__init__()

    def get_project_path(self, project_id: str):
        project_dir = os.path.join(
            self.files_dir,
            str(project_id)
        )

        if not os.path.exists(project_dir):
            os.makedirs(project_dir)

        return project_dir

    def get_project_subdir(self, project_id: str, name: str):
        subdir = os.path.join(
            self.get_project_path(project_id=project_id),
            name
        )

        if not os.path.exists(subdir):
            os.makedirs(subdir)

        return subdir

    def delete_project_files(self, project_id: str):
        project_dir = os.path.join(
            self.files_dir,
            str(project_id)
        )

        if not os.path.exists(project_dir):
            logger.info(f"No project files to delete for project_id={project_id}")
            return False

        shutil.rmtree(project_dir)
        logger.info(f"Deleted project files for project_id={project_id}")
        return True

    
