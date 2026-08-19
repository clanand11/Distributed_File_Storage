import os
import uuid
import httpx

from fastapi import FastAPI, UploadFile, File , Depends, HTTPException
from fastapi.responses import Response

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

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://127.0.0.1:9001/store",
            params={
                "file_id" : file_id
            },
            files = {
                "file" : (
                    file.filename,
                    await file.read(),
                    file.content_type
                )
            }
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail="Storage node failed to store the file"
        )

    contents_size = response.headers.get("content-length")

    new_file = FileModel(
        id = file_id,
        filename=file.filename,
        path=f"node1_data/{file_id}",
        size=0,
        content_type=file.content_type,
        node_id = "node1"
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)


    return{
        "id": file_id,
        "filename" : file.filename,
        "node_id": "node1",
        "message" : "File uploaded successfully"
    }


@app.get("/files/{file_id}")
async def download_file(file_id: str, 
                  db : Session = Depends(get_db)
                  ):

    file_info = db.query(FileModel).filter(FileModel.id == file_id).first()
    
    if not file_info:
        raise HTTPException(
            status_code=404,
            detail="File Not Found"
        )

    node_url = "http://127.0.0.1:9001"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{node_url}/retrieve/{file_id}"
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=500,
            detail="Storage node failed to retrieve file"
        )

    return Response(
        content = response.content,
        media_type = file_info.content_type,
        headers={
            'Content-Disposition' : f'attachment; filename="{file_info.filename}"'
        }
    )


@app.delete("/files/{file_id}")
async def delete_file(file_id : str,
                db : Session = Depends(get_db)
                ):

    file_info = db.query(FileModel).filter(FileModel.id == file_id).first()

    if not file_info:
            raise HTTPException(
                status_code=404,
                detail="File Not Found"
            )

    node_url = "http://127.0.0.1:9001"

    async with httpx.AsyncClient() as client:

        response = await client.delete(
            f'{node_url}/delete/{file_id}'
        ) 

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="File not found on storage node"
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail="Storage node failed to delete file"
        )

    db.delete(file_info)
    db.commit()

    return {
        "message" : "File deleted successfully",
        "file_id" : file_id
    }
