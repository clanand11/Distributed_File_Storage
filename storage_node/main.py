from fastapi import FastAPI, UploadFile, File
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