from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import os

app = FastAPI()

NODE_STORAGE = "storage_node/node1_data"

os.makedirs(NODE_STORAGE, exist_ok=True)


@app.get("/health")
def health():
    return {
        "status" : "healthy"
    }


@app.post("/store")
async def store_file(
    file_id : str,
    file : UploadFile = File(...)
):
    file_path = os.path.join(NODE_STORAGE, file_id)

    contents = await file.read()

    with open(file_path, "wb") as f:
        f.write(contents)

    return {
        "message" : "File Stored Successfully",
        "file_id" : file_id
    }


@app.get("/retrieve/{file_id}")
def retrieve_file(file_id : str):
    file_path = os.path.join(NODE_STORAGE,file_id)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="File not found on storage node"
        )

    return FileResponse(path=file_path)


@app.delete("/delete/{file_id}")
def delete_file(file_id : str):

    file_path = os.path.join(NODE_STORAGE,file_id)

    if not os.path.exists(file_path):
        raise HTTPException(   
            status_code=404,
            detail="File not found on storage node"
        )

    os.remove(file_path)

    return{
        "message" : "File deleted from storage node",
        "file_id" : file_id
    }