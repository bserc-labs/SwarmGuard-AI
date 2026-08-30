import time
from datetime import datetime

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

from config import get_settings
from models_ml.dataset_loader import DatasetLoader
from models_ml.experiment_tracker import experiment_tracker
from models_ml.preprocess import FeatureEngineer
from models_ml.registry import model_registry
from utils.logger import logger

settings = get_settings()

def set_reproducibility():
    """Enforces deterministic behavior where possible."""
    np.random.seed(settings.RANDOM_SEED)

def evaluate_model_metrics(y_true, y_pred, y_scores):
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    try:
        roc_auc = roc_auc_score(y_true, y_scores)
    except ValueError:
        roc_auc = 0.0
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "roc_auc": float(roc_auc),
        "false_positive_rate": float(fpr),
        "false_negative_rate": float(fnr),
        "confusion_matrix": {"TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp)}
    }

def train_and_evaluate(name, model_instance, X_train, X_test, y_test, requires_decision_func=True):
    logger.info(f"Training {name}...")
    
    t0 = time.perf_counter()
    if name == "LocalOutlierFactor":
        # LOF fits and predicts on training for novelty detection if novelty=True
        model_instance.fit(X_train)
    else:
        model_instance.fit(X_train)
    t_train = time.perf_counter() - t0
    
    t0 = time.perf_counter()
    y_pred_raw = model_instance.predict(X_test)
    t_infer = time.perf_counter() - t0
    
    y_pred = (y_pred_raw == -1).astype(int)
    
    if requires_decision_func and hasattr(model_instance, "decision_function"):
        y_scores = -model_instance.decision_function(X_test)
    else:
        # For LOF, if novelty=True, decision_function is available
        if hasattr(model_instance, "decision_function"):
            y_scores = -model_instance.decision_function(X_test)
        else:
            y_scores = np.zeros_like(y_pred)
            
    metrics = evaluate_model_metrics(y_test, y_pred, y_scores)
    metrics["training_time_seconds"] = t_train
    metrics["inference_time_seconds"] = t_infer
    return metrics, model_instance

def run_training_pipeline():
    logger.info("Starting AI Training Pipeline with Scientific Rigor...")
    set_reproducibility()
    pipeline_start_time = time.perf_counter()
    
    loader = DatasetLoader()
    df = loader.load_and_clean()
    
    engineer = FeatureEngineer()
    df_features = engineer.transform(df)
    feature_cols = engineer.get_feature_columns()
    df_features = df_features.dropna(subset=feature_cols)
    
    X = df_features[feature_cols].values
    y = df_features["label"].values
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=settings.RANDOM_SEED)
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    results = {}
    models = {}
    
    # 1. Isolation Forest (Primary)
    if_model = IsolationForest(contamination=settings.CONTAMINATION, random_state=settings.RANDOM_SEED, n_jobs=-1)
    results["IsolationForest"], models["IsolationForest"] = train_and_evaluate(
        "IsolationForest", if_model, X_train_scaled, X_test_scaled, y_test
    )
    
    # 2. Local Outlier Factor (Baseline)
    # LOF requires novelty=True for predict() on new data
    lof_model = LocalOutlierFactor(contamination=settings.CONTAMINATION, novelty=True, n_jobs=-1)
    results["LocalOutlierFactor"], models["LocalOutlierFactor"] = train_and_evaluate(
        "LocalOutlierFactor", lof_model, X_train_scaled, X_test_scaled, y_test
    )
    
    # 3. One-Class SVM (Academic Baseline, reduced subset if dataset is huge)
    MAX_SVM_SAMPLES = 5000
    if len(X_train_scaled) > MAX_SVM_SAMPLES:
        logger.info("Reducing training set for OCSVM to fit in memory/time...")
        X_train_svm = X_train_scaled[:MAX_SVM_SAMPLES]
    else:
        X_train_svm = X_train_scaled
        
    ocsvm_model = OneClassSVM(nu=settings.CONTAMINATION, kernel="rbf", gamma="scale")
    results["OneClassSVM"], models["OneClassSVM"] = train_and_evaluate(
        "OneClassSVM", ocsvm_model, X_train_svm, X_test_scaled, y_test
    )
    
    # Log Comparison Table
    logger.info("--- Model Comparison ---")
    for name, r in results.items():
        logger.info(f"{name} -> F1: {r['f1_score']:.3f}, Recall: {r['recall']:.3f}, Train Time: {r['training_time_seconds']:.3f}s")
        
    # Programmatic Selection: Prefer IsolationForest unless LOF beats its F1 by > 0.05
    best_model_name = "IsolationForest"
    if results["LocalOutlierFactor"]["f1_score"] > results["IsolationForest"]["f1_score"] + 0.05:
        best_model_name = "LocalOutlierFactor"
        
    logger.info(f"Selected Production Model: {best_model_name}")
    
    final_model = models[best_model_name]
    final_metrics = results[best_model_name]
    
    version = settings.MODEL_VERSION
    metadata = {
        "model_version": version,
        "training_timestamp": datetime.utcnow().isoformat(),
        "dataset_source": settings.DATASET_PATH,
        "feature_list": feature_cols,
        "algorithm": best_model_name,
        "selection_evidence": {
            "IsolationForest_F1": results["IsolationForest"]["f1_score"],
            "LocalOutlierFactor_F1": results["LocalOutlierFactor"]["f1_score"],
            "OneClassSVM_F1": results["OneClassSVM"]["f1_score"]
        }
    }
    
    training_config = {
        "contamination_factor": settings.CONTAMINATION,
        "random_seed": settings.RANDOM_SEED,
        "preprocessing_configuration": settings.SCALING_METHOD,
        "feature_engineering_configuration": f"Rolling Window = {settings.WINDOW_SIZE}"
    }
    
    model_registry.save_model(
        version=version,
        model=final_model,
        scaler=scaler,
        metadata=metadata,
        training_config=training_config,
        evaluation=final_metrics
    )
    
    total_time = time.perf_counter() - pipeline_start_time
    experiment_tracker.record_experiment(
        dataset_source=settings.DATASET_PATH,
        feature_list=feature_cols,
        contamination=settings.CONTAMINATION,
        random_seed=settings.RANDOM_SEED,
        evaluation_metrics=final_metrics,
        model_version=version,
        execution_time_seconds=total_time
    )
    
    logger.info(f"Training Pipeline Complete. Model {version} is ready for inference.")

if __name__ == "__main__":
    run_training_pipeline()
