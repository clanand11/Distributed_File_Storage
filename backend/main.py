import os
import uuid
import httpx
import asyncio

from dotenv import load_dotenv
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File , Depends, HTTPException
from fastapi.responses import Response

from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import FileModel

from fastapi.middleware.cors import CORSMiddleware

load_dotenv()


STORAGE_NODES = {
    "node1": os.getenv("NODE1_URL"),
    "node2": os.getenv("NODE2_URL"),
    "node3": os.getenv("NODE3_URL")
}

if any(url is None for url in STORAGE_NODES.values()):
    raise RuntimeError("Storage node configuration is missing")

NODE_LIST = list(STORAGE_NODES.keys())
current_node = 0

NODE_STATUS = {
    node_id: False
    for node_id in STORAGE_NODES
}


def get_next_node():
    global current_node

    for _ in range(len(NODE_LIST)):
        node_id = NODE_LIST[current_node]

        current_node = (current_node + 1) % len(NODE_LIST)

        if NODE_STATUS[node_id]:
            return node_id

    return None

def get_replica_node(primary_node_id):

    primary_index = NODE_LIST.index(primary_node_id)

    for i in range(1,len(NODE_LIST)):

        replica_index = (primary_index + i) % len(NODE_LIST)

        replica_node_id = NODE_LIST[replica_index] 

        if NODE_STATUS[replica_node_id]:
            return replica_node_id

    return None
        


async def check_node_health(node_id:str, node_url: str):

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{node_url}/health"
            )
            
            if response.status_code == 200:
                return True

    except httpx.RequestError as e:
        print(f"[HEALTH ERROR] {node_id}: {repr(e)}")


    return False


async def monitor_nodes():

    while True:

        try:
            for node_id, node_url in STORAGE_NODES.items():

                NODE_STATUS[node_id] = await check_node_health(node_id,node_url)

            await process_pending_deletions()

            await recover_missing_replicas()

        except Exception as e:
            print(f"[Monitor Error] {repr(e)}")

        await asyncio.sleep(10)



async def process_pending_deletions():

    db = SessionLocal()

    try:

        pending_files = db.query(FileModel).filter(
            FileModel.deletion_pending == True
        ).all()

        async with httpx.AsyncClient(timeout=10.0) as client:

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


async def recover_missing_replicas():

    db = SessionLocal()

    try:
        files = db.query(FileModel).filter(FileModel.deletion_pending == False).all()

        async with httpx.AsyncClient(timeout=10.0) as client:

            for file_info in files:

                primary_node_id = file_info.node_id
                replica_node_id = file_info.replica_node_id

                primary_url = STORAGE_NODES.get(primary_node_id)
                replica_url = STORAGE_NODES.get(replica_node_id)

                if not primary_url or not replica_url:
                    continue

                if not NODE_STATUS.get(primary_node_id, False):
                    continue

                if not NODE_STATUS.get(replica_node_id, False):
                    continue

                try:
                    response = await client.get(
                        f"{replica_url}/retrieve/{file_info.id}"
                    )

                    if response.status_code == 200:
                        continue

                except httpx.RequestError:
                    continue

                try:
                    response = await client.get(
                        f"{primary_url}/retrieve/{file_info.id}"
                    )

                    if response.status_code != 200:
                        continue
                except httpx.RequestError:
                    continue

                try:

                    store_response = await client.post(
                        f"{replica_url}/store",
                        params={
                            "file_id": file_info.id
                        },
                        files={
                            "file": (
                                file_info.filename,
                                response.content,
                                file_info.content_type
                            )
                        }
                    )

                    if store_response.status_code == 200:

                        print(
                            f"Replica recovered: "
                            f"{file_info.id} → "
                            f"{replica_node_id}"
                        )

                except httpx.RequestError:
                    continue

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

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

    if not primary_node_id:
        raise HTTPException(
            status_code=503,
            detail="No healthy storage nodes available"
        )

    primary_node_url = STORAGE_NODES[primary_node_id]

    replica_node_id = get_replica_node(primary_node_id)

    if not replica_node_id:
        raise HTTPException(
            status_code=503,
            detail="No healthy replica node available"
        )

    replica_node_url = STORAGE_NODES[replica_node_id]

    async with httpx.AsyncClient(timeout=10.0) as client:

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

        try:
            db.add(new_file)
            db.commit()
            db.refresh(new_file)
        except Exception:
            db.rollback()

            try:
                await client.delete(
                f"{primary_node_url}/delete/{file_id}"
                )
            except httpx.RequestError:
                pass

            try:
                await client.delete(
                    f"{replica_node_url}/delete/{file_id}"
                )
            except httpx.RequestError:
                pass

            raise HTTPException(
                status_code=500,
                detail="Database operation failed; upload rolled back"
            )

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

    async with httpx.AsyncClient(timeout=10.0) as client:
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

    async with httpx.AsyncClient(timeout=10.0) as client:

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