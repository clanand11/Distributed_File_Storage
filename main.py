import os
import uuid

from fastapi import FastAPI, UploadFile, File , Depends, HTTPException
from fastapi.responses import FileResponse

from sqlalchemy.orm import Session
from database import get_db
from models import FileModel

app =FastAPI()

STORGAE_DIR = "storage"
os.makedirs(STORGAE_DIR, exist_ok=True)


@app.get("/")
def home():
    return {"message" : "File storage api"}


@app.get("/files")
def list_files(db: Session = Depends(get_db)):

    files = db.query(FileModel).all()

    return files



@app.post("/upload")
async def upload_file(
                    file: UploadFile = File(...),
                    db : Session = Depends(get_db)
                ):
    
    file_id=str(uuid.uuid4())

    file_path = os.path.join(STORGAE_DIR, f"{file_id}_{file.filename}")

    contents = await file.read()

    with open(file_path,"wb") as f:
        f.write(contents)

    new_file = FileModel(
        id = file_id,
        filename=file.filename,
        path=file_path,
        size=len(contents),
        content_type=file.content_type 
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)


    return{
        "id": file_id,
        "filename" : file.filename,
        "message" : "File uploaded successfully"
    }


@app.get("/files/{file_id}")
def download_file(file_id: str, 
                  db : Session = Depends(get_db)
                  ):

    file_info = db.query(FileModel).filter(FileModel.id == file_id).first()
    
    if not file_info:
        raise HTTPException(
            status_code=404,
            detail="File Not Found"
        )

    return FileResponse(
        path=file_info.path,
        filename=file_info.filename
    )


@app.delete("/files/{file_id}")
def delete_file(file_id : str,
                db : Session = Depends(get_db)
                ):

    file_info = db.query(FileModel).filter(FileModel.id == file_id).first()

    if not file_info:
            raise HTTPException(
                status_code=404,
                detail="File Not Found"
            )

    if os.path.exists(file_info.path):
        os.remove(file_info.path)

    db.delete(file_info)
    db.commit()

    return {
        "message" : "File deleted successfully"
    }
