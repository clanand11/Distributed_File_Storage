# Distributed File Storage System

## Current Features

- File upload
- File listing
- File download
- File deletion
- PostgreSQL-based file metadata storage
- RESTful APIs using FastAPI

## Tech Stack

- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Uvicorn

## Current Architecture

Client
   |
   v
FastAPI
   |
   +---- PostgreSQL (file metadata)
   |
   +---- Local Storage (file data)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload a file |
| GET | `/files` | List files |
| GET | `/files/{id}` | Download a file |
| DELETE | `/files/{id}` | Delete a file |

## Project Status

### Phase 1 — Basic File Storage API ✅

- [x] File upload
- [x] File listing
- [x] File download
- [x] File deletion
- [x] PostgreSQL integration

### Phase 2 — Distributed Storage 🚧

- [ ] Storage nodes
- [ ] Node communication
- [ ] File replication
- [ ] Failure detection
- [ ] Fault tolerance
- [ ] Docker deployment