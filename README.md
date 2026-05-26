# DnD Planner

DnD Planner is a small shared calendar for tabletop groups. Players pick a month, click days to mark themselves as `Available`, `Maybe`, or `No`, and the app shows the group's combined availability so it is easier to find a session date.

It also includes a few admin views:
- a personal admin calendar
- a cross-group overview for comparing two groups
- a "oneshot recruiter" view that finds days where one full group can host and another group has possible guests

## How to run it

### Backend

From the project root:

```bash
source venv/bin/activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

If you do not already have the Python packages installed:

```bash
pip install -r requirements.txt
```

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Then open `http://localhost:3000`.

## How it works

- The frontend is a Next.js app in [`frontend/`](./frontend) that renders the calendars and admin views.
- The backend is a FastAPI app in [`backend/`](./backend) that exposes endpoints for groups and availability.
- Next.js rewrites `/api/*` requests to `http://127.0.0.1:8000/*`, so the browser talks to the frontend and the frontend forwards API calls to FastAPI.
- Availability is stored in the SQLite file `dnd_planner.db`.
- The built-in groups and player names are currently hardcoded in [`backend/database.py`](./backend/database.py).

## Notes

- Clicking a day cycles through `Available -> Maybe -> No -> clear`.
- Right-clicking a day opens a quick status menu.
- `start_app.sh` starts both services together, but it uses `npm run start`, so it expects the frontend to already be built for production.
