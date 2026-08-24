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

STORAGE_NODES = {
    "node1": "http://127.0.0.1:9001",
    "node2": "http://127.0.0.1:9002",
    "node3": "http://127.0.0.1:9003"
}

NODE_LIST = list(STORAGE_NODES.keys())
current_node = 0


def get_next_node():
    global current_node

    node_id = NODE_LIST[current_node]

    current_node = (current_node + 1) % len(NODE_LIST)

    return node_id


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

    file_contents = await file.read()

    primary_node_id = get_next_node()
    primary_node_url = STORAGE_NODES[primary_node_id]

    primary_index = NODE_LIST.index(primary_node_id)
    replica_index = (primary_index + 1) % len(NODE_LIST)

    replica_node_id = NODE_LIST[replica_index]
    replica_node_url = STORAGE_NODES[replica_node_id]

    async with httpx.AsyncClient() as client:

        primary_response = await client.post(
            f"{primary_node_url}/store",
            params={
                "file_id": file_id
            },
            files={
                "file": (
                    file.filename,
                    file_contents,
                    file.content_type
                )
            }
        )

        if primary_response.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail="Primary storage node failed to store the file"
            )  

        replica_response = await client.post(
                    f"{replica_node_url}/store",
                    params={
                        "file_id": file_id
                    },
                    files={
                        "file": (
                            file.filename,
                            file_contents,
                            file.content_type
                        )
                    }
                )
        
        if replica_response.status_code != 200:

            await client.delete(
                f"{primary_node_url}/delete/{file_id}"
            )

            raise HTTPException(
                status_code=500,
                detail="Replica storage node failed to store the file"
            )    

    new_file = FileModel(
        id=file_id,
        filename=file.filename,
        path=f"{primary_node_id}_data/{file_id}",
        size=len(file_contents),
        content_type=file.content_type,
        node_id=primary_node_id,
        replica_node_id=replica_node_id
    ) 

    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return {
        "id": file_id,
        "filename": file.filename,
        "primary_node": primary_node_id,
        "replica_node": replica_node_id,
        "message": "File uploaded and replicated successfully"
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

    node_url = STORAGE_NODES.get(file_info.node_id)

    if not node_url:
        raise HTTPException(
        status_code=500,
        detail="Invalid storage node"
        )

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

    node_url = STORAGE_NODES.get(file_info.node_id)

    if not node_url:
        raise HTTPException(
            status_code=500,
            detail="Invalid storage node"
        )

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
