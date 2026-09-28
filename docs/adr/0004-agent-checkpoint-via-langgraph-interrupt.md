# Agent Checkpoints use LangGraph interrupts with a Postgres checkpointer

A Campaign reaches its Checkpoint by calling LangGraph `interrupt()`. State is persisted by `langgraph-checkpoint-postgres` under `thread_id = campaign_id`, and the Celery task then ends. A Recruiter Decision enqueues a new task that resumes the graph with `Command(resume=decision)`. A human may take hours to decide, and holding a worker slot for that long would starve the queue.

## Consequences

- The 15-minute Campaign budget measures machine time only and excludes time spent waiting at a Checkpoint.
- Before the Checkpoint the agent may create derived data (Scoring Runs, Score Results, What-if Suggestions). It may not change Stages, create Applications, or change Job criteria or weights. Those happen only when the Recruiter Decision is applied, in the resume task, attributed to that Recruiter.
