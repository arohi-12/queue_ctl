
# QueueCTL

> A CLI-based background job queue system built in Python with persistent SQLite storage, concurrent workers, retry handling using exponential backoff, configuration management, and a Dead Letter Queue (DLQ).

## Objective

QueueCTL was developed as a solution for the **Backend Developer Internship Assignment**. The goal is to provide a lightweight but production-inspired background job processing system that supports persistent storage, concurrent workers, automatic retries, graceful shutdown, and CLI-based management.

---

# Assignment Requirement Checklist

| Requirement | Status |
|------------|:------:|
| CLI Application | ✅ |
| Persistent Job Storage | ✅ (SQLite) |
| Multiple Workers | ✅ |
| Retry Mechanism | ✅ |
| Exponential Backoff | ✅ |
| Dead Letter Queue | ✅ |
| Configuration Management | ✅ |
| Graceful Worker Shutdown | ✅ |
| Locking / Duplicate Prevention | ✅ |
| Testing | ✅ |
| Comprehensive README | ✅ |

---

# Features

- SQLite-backed persistent storage
- Click-based CLI
- Concurrent worker support
- Atomic job claiming
- Retry with exponential backoff
- Dead Letter Queue (DLQ)
- Job inspection
- Queue status
- Configuration persistence
- Recovery of stale jobs
- Purging completed/DLQ jobs
- Job output and error logging
- Cross-platform (Windows/Linux/macOS)

---

# Architecture Overview

```text
                 User
                   │
                   ▼
            queuectl CLI
                   │
            Click Command Parser
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
 JobStore      Config       Worker Manager
     │                            │
     └─────────────┬──────────────┘
                   ▼
             SQLite Database
                   │
             Pending Jobs
                   │
              Worker Claims
                   │
          Execute Subprocess
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
   Completed             Failed
                              │
                       Exponential Backoff
                              │
                  Retry Available?
                      │      │
                     Yes     No
                      │      │
                      ▼      ▼
                  Pending   DLQ
```

---

# Project Structure

```text
queuectl/
├── __main__.py
├── cli.py
├── config.py
├── models.py
├── store.py
├── worker.py
├── utils.py
└── _runner.py

tests/
├── test_store.py
├── test_worker.py
└── test_integration.py

requirements.txt
setup.py
validate.sh
```

---

# Installation

```bash
git clone https://github.com/2k23csaiml2313622-code/Flam-Queue-CTL.git
cd Flam-Queue-CTL
```

Create a virtual environment:

**Windows**

```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/macOS**

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Running QueueCTL

Run the package using Python's module mode:

```bash
python -m queuectl <command>
```

Examples:

```bash
python -m queuectl status
python -m queuectl list
python -m queuectl worker start --count 2
python -m queuectl worker stop
```

---

# Enqueue Example

Windows PowerShell:

```powershell
python -m queuectl enqueue "{\"command\":\"echo Hello World\"}"
```

Linux/macOS:

```bash
python -m queuectl enqueue '{"command":"echo Hello World"}'
```

## Why use `python -m queuectl`?

The CLI entry point is implemented inside the Python package (`queuectl/__main__.py`). Running the package with `python -m queuectl` ensures Python loads the package correctly, resolves relative imports, and invokes the intended CLI entry point.

## Why quote the JSON?

The `enqueue` command expects **one JSON string argument**. PowerShell interprets braces (`{}`) as script block syntax unless they are quoted. Wrapping the JSON in quotes ensures the entire JSON object is passed as a single string to the CLI, where it can be parsed correctly.

---

# CLI Commands

| Command | Description |
|---------|-------------|
| `enqueue` | Add a job |
| `worker start --count N` | Start workers |
| `worker stop` | Gracefully stop workers |
| `status` | Queue summary |
| `list` | List jobs |
| `inspect <id>` | View job details |
| `dlq list` | Show dead jobs |
| `dlq retry <id>` | Retry a dead job |
| `recover` | Recover stale processing jobs |
| `purge` | Remove completed/DLQ jobs |
| `config get/set/reset` | Manage configuration |

---

# Job Lifecycle

```text
Pending
   │
   ▼
Processing
   │
   ├────────► Completed
   │
   ▼
Failed
   │
Retry (delay = base^attempts)
   │
   ▼
Pending
   │
(Max retries exceeded)
   ▼
Dead Letter Queue
```

---

# Persistence

SQLite stores all job metadata, retry counts, timestamps, outputs, and states. Jobs survive application restarts and can be resumed without data loss.

---

# Worker Logic

1. Poll queue.
2. Atomically claim a pending job.
3. Execute command.
4. Record output and exit code.
5. Mark completed on success.
6. Retry with exponential backoff on failure.
7. Move to DLQ after maximum retries.

---

# Retry Strategy

Delay is calculated as:

```text
delay = backoff_base ^ attempts
```

Example (base = 2):

| Attempt | Delay |
|---------:|------:|
|1|2 s|
|2|4 s|
|3|8 s|

---

# Assumptions & Trade-offs

- SQLite was chosen for simplicity and persistence.
- Suitable for lightweight/local queue management rather than distributed deployments.
- Atomic SQLite transactions prevent duplicate processing.
- CLI-first design keeps deployment simple and dependency footprint low.

---

# Testing

Run all tests:

```bash
pytest
```

Run individual suites:

```bash
pytest tests/test_store.py
pytest tests/test_worker.py
pytest tests/test_integration.py
```

---

# Validation

If provided:

```bash
./validate.sh
```

---

# Bonus Features Implemented

- Job priority field
- Scheduled (`run_at`) jobs
- Graceful shutdown
- Stale job recovery
- Job output logging
- Configuration persistence
- Purge commands
- Windows compatibility improvements

---

# Future Improvements

- Redis backend
- Docker support
- REST API
- Web dashboard
- Metrics
- Queue visualization
- Distributed workers

---## Demo Video

Google Drive Link:
https://drive.google.com/file/d/1W-tfMVShUtPTj3iXueir-jT97Ox20FUh/view?usp=drive_link



# Author

**Arohi Agarwal**

B.Tech – Computer Science (AIML)

Backend Developer Internship Assignment – QueueCTL
