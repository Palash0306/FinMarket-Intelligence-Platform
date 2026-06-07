# path: app/ml/utils/mlflow_helper.py

# =========================================================
# MLFLOW HELPER
# =========================================================
#
# What is MLflow in plain English?
#
# Every time you train a model, MLflow saves:
# - Parameters: what settings you used
# - Metrics: how accurate the model was (MAE, RMSE)
# - Model: the actual trained model file
# - Artifacts: plots, feature importance charts
#
# Think of it as a lab notebook for ML experiments.
# You can compare different runs and see which was best.
#
# Access the MLflow UI at: http://localhost:5001
# (we add it to docker-compose.yml)
#
# Connection chain:
# prophet_model.py → mlflow_helper → MLflow server
# xgb_model.py    → mlflow_helper → MLflow server
#       ↓ model artifacts saved to
# S3 bucket (finmarket-raw-data-palash/mlflow/)
# OR local ./mlruns/ folder

import mlflow
import mlflow.sklearn
import mlflow.xgboost
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def setup_mlflow() -> None:
    """
    Configures MLflow tracking URI.

    Local development: saves to ./mlruns/ folder
    Production: would point to a remote server

    Call this once before any mlflow operations.
    """
    # Local tracking — saves experiment data in ./mlruns/
    # Change to a remote URI in production
    mlflow.set_tracking_uri("./mlruns")
    logger.info("mlflow_configured")


def log_model_run(
    experiment_name: str,
    run_name: str,
    params: dict,
    metrics: dict,
    model=None,
    model_type: str = "sklearn"
) -> str:
    """
    Logs one model training run to MLflow.

    Args:
        experiment_name: groups related runs e.g. "prophet_AAPL"
        run_name:        this specific run e.g. "2024-01-15_run"
        params:          model settings e.g. {"changepoint_scale": 0.05}
        metrics:         accuracy measures e.g. {"mae": 2.34, "rmse": 3.1}
        model:           trained model object to save
        model_type:      "sklearn", "xgboost", or "prophet"

    Returns:
        run_id: unique ID for this run (used to load the model later)

    In plain English:
    Like saving a Word document with a unique filename.
    Later you can open that exact version.
    """
    setup_mlflow()

    # Get or create the experiment
    # (like a folder for related runs)
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name=run_name) as run:

        # Log parameters (what settings were used)
        if params:
            mlflow.log_params(params)

        # Log metrics (how well the model performed)
        if metrics:
            mlflow.log_metrics(metrics)

        # Save the model itself
        if model is not None:
            if model_type == "xgboost":
                mlflow.xgboost.log_model(model, "model")
            else:
                mlflow.sklearn.log_model(model, "model")

        run_id = run.info.run_id

        logger.info(
            "mlflow_run_logged",
            extra={
                "experiment": experiment_name,
                "run_id": run_id,
                "metrics": metrics
            }
        )

        return run_id