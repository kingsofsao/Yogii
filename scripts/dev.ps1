param (
    [Parameter(Mandatory=$true)]
    [string]$Command
)

switch ($Command) {
    "migrate" {
        & .\backend\venv\Scripts\alembic.exe upgrade head
    }
    "seed" {
        & .\backend\venv\Scripts\python.exe -m backend.scripts.seed
    }
    "train-model" {
        & .\backend\venv\Scripts\python.exe -m backend.ml.train
    }
    "test" {
        & .\backend\venv\Scripts\pytest.exe backend\tests -v
    }
    "run-api" {
        & .\backend\venv\Scripts\uvicorn.exe backend.main:app --reload --port 8000
    }
    "run-web" {
        cd frontend
        npm run dev
    }
    "build-web" {
        cd frontend
        npm run build
    }
    Default {
        Write-Host "Unknown command: $Command"
        Write-Host "Available: migrate, seed, train-model, test, run-api, run-web, build-web"
    }
}
