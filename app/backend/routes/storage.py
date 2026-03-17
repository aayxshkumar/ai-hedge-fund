import re

from fastapi import APIRouter, HTTPException
import json
from pathlib import Path
from pydantic import BaseModel

from app.backend.models.schemas import ErrorResponse

router = APIRouter(prefix="/storage")

_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9_\-][a-zA-Z0-9_\-./]*$")

class SaveJsonRequest(BaseModel):
    filename: str
    data: dict

@router.post(
    path="/save-json",
    responses={
        200: {"description": "File saved successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def save_json_file(request: SaveJsonRequest):
    """Save JSON data to the project's /outputs directory."""
    try:
        project_root = Path(__file__).parent.parent.parent.parent
        outputs_dir = project_root / "outputs"
        outputs_dir.mkdir(exist_ok=True)

        if not _SAFE_FILENAME.match(request.filename) or ".." in request.filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        file_path = (outputs_dir / request.filename).resolve()
        if not str(file_path).startswith(str(outputs_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(request.data, f, indent=2, ensure_ascii=False)
        
        return {
            "success": True,
            "message": f"File saved successfully",
            "filename": request.filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}") 