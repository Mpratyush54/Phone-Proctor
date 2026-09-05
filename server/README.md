# Phone-Proctor Central Server

Minimal Node control plane for the product path.

## Run (zero DB required)

```bash
cd server
npm install
npm start
```

- Health: `http://localhost:8080/health`
- Agent WS: `ws://localhost:8080/agent`
- Examiner room: `ws://localhost:8080/exam/<sessionId>`
- Examiner UI: `http://localhost:8080/admin/`

Mongo/Redis are optional later (`optionalDependencies`). Default store is **in-memory**.

## Agent

```bash
python main.py --server ws://127.0.0.1:8080/agent --exam-code DEMO --student-id S1
```

Copy the printed session id into the examiner UI to watch live events.
