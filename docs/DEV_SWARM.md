# Dev Swarm Documentation

## Pipeline
The Dev Swarm operates on a structured linear pipeline to ensure code quality and reliability:
1. **Plan**: Define the requirements and architecture.
2. **Code**: Implement the logic based on the plan.
3. **Review**: Peer review of the implemented code.
4. **Test**: Automated and manual verification.
5. **User Approval**: Final human sign-off.
6. **Promote**: Deployment sequence from `dev` -> `master` -> `retail`.

## Infrastructure
- **Local Execution**: Only local models are used for all operations.
- **VRAM Management**: To optimize resources, only one model is loaded into VRAM at any given time.

## Approval Policy
- **Human-in-the-loop**: Only the user provides final approval for any changes.
- **No Self-Approval**: Agents are strictly prohibited from approving their own code; every contribution must be validated by a human.