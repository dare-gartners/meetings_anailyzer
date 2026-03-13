# Meeting Notes AI

Small MVP app that turns meeting notes into:
- summary
- action items
- tags

## MVP scope
User pastes notes into a web page and gets structured output.

## Out of scope for now
- authentication
- database
- multi-user support
- analytics dashboard
- vector database
- agents

## Stack
- Python
- FastAPI
- HTML
- Azure OpenAI (`openai` SDK, `AzureOpenAI` client)

## Environment variables
```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_MODEL_VERSION=2024-02-01
```