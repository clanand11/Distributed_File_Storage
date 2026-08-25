import os
import uuid
import httpx
import asyncio

from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File , Depends, HTTPException
from fastapi.responses import Response

from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import FileModel


STORGAE_DIR = "storage"
os.makedirs(STORGAE_DIR, exist_ok=True)

STORAGE_NODES = {
    "node1": "http://127.0.0.1:9001",
    "node2": "http://127.0.0.1:9002",
    "node3": "http://127.0.0.1:9003"
}

NODE_LIST = list(STORAGE_NODES.keys())
current_node = 0

NODE_STATUS = {
    node_id: False
    for node_id in STORAGE_NODES
}


def get_next_node():
    global current_node

    node_id = NODE_LIST[current_node]

    current_node = (current_node + 1) % len(NODE_LIST)

    return node_id


async def check_node_health(node_id:str, node_url: str):

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(
                f"{node_url}/health"
            )

            # print(
            #     f"{node_id} → "
            #     f"{response.status_code} → "
            #     f"{response.text}"
            # )

            if response.status_code == 200:
                return True

    except httpx.RequestError:
        pass

    # except  Exception as e:
    #     print(
    #         f"{node_id} -> Error -> {repr(e)}"
    #     )

    return False


async def monitor_nodes():
    while True:
        for node_id, node_url in STORAGE_NODES.items():

            NODE_STATUS[node_id] = await check_node_health(node_id,node_url)

        await process_pending_deletions()

        await asyncio.sleep(10)

async def process_pending_deletions():

    db = SessionLocal()

    try:

        pending_files = db.query(FileModel).filter(
            FileModel.deletion_pending == True
        ).all()

        async with httpx.AsyncClient(timeout=5.0) as client:

            for file_info in pending_files:

                nodes = [
                    file_info.node_id,
                    file_info.replica_node_id
                ]

                all_deleted = True

                for node_id in nodes:

                    if not NODE_STATUS.get(node_id, False):
                        all_deleted = False
                        continue

                    node_url = STORAGE_NODES[node_id]

                    try:

                        response = await client.delete(
                            f"{node_url}/delete/{file_info.id}"
                        )

                        if response.status_code not in [200, 404]:
                            all_deleted = False

                    except httpx.RequestError:

                        all_deleted = False

                if all_deleted:

                    db.delete(file_info)

            db.commit()

    finally:

        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    monitoring_task = asyncio.create_task(monitor_nodes())

    yield

    monitoring_task.cancel()

    try:
        await monitoring_task
    except asyncio.CancelledError:
        pass

app =FastAPI(lifespan=lifespan)

@app.get("/nodes/status")
def node_status():

    return NODE_STATUS



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

    primary_url = STORAGE_NODES.get(file_info.node_id)
    replica_url = STORAGE_NODES.get(file_info.replica_node_id)

    if not primary_url:
        raise HTTPException(
        status_code=500,
        detail="Invalid primary storage node"
        )
    
    if not replica_url:
        raise HTTPException(
        status_code=500,
        detail="Invalid replica storage node"
        )

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{primary_url}/retrieve/{file_id}"
            )

            if response.status_code == 200:
                return Response(
                    content=response.content,
                    media_type=file_info.content_type,
                    headers={
                        "Content-Disposition":
                        f'attachment; filename="{file_info.filename}"'
                    }
                )

        except httpx.RequestError:
            pass

        try:
            response = await client.get(
                f"{replica_url}/retrieve/{file_id}"
            )

            if response.status_code == 200:
                return Response(
                    content=response.content,
                    media_type=file_info.content_type,
                    headers={
                        "Content-Disposition":
                        f'attachment; filename="{file_info.filename}"'
                    }
                )

        except httpx.RequestError:
            pass

    raise HTTPException(
        status_code=503,
        detail="File unavailable on both storage nodes"
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

    primary_url = STORAGE_NODES.get(file_info.node_id)
    replica_url = STORAGE_NODES.get(file_info.replica_node_id)

    if not primary_url or not replica_url:
        raise HTTPException(
            status_code=500,
            detail="Invalid storage node"
        )

    async with httpx.AsyncClient() as client:

        primary_deleted = False
        replica_deleted = False

        try:
            response = await client.delete(
                f"{primary_url}/delete/{file_id}"
            )

            if response.status_code in [200,404]:
                primary_deleted = True

        except httpx.RequestError:
            pass

        try: 
            response = await client.delete(
                f"{replica_url}/delete/{file_id}"
            )

            if response.status_code in [200,404]:
                replica_deleted = True

        except httpx.RequestError:
            pass

    if primary_deleted and replica_deleted:
        
        db.delete(file_info)
        db.commit()

        return {
            "message": "File deleted successfully from all replicas",
            "file_id": file_id
        }

    file_info.deletion_pending = True

    db.commit()

    return {
        "message": "File deletion pending until unavailable node recovers",
        "file_id": file_id
    }