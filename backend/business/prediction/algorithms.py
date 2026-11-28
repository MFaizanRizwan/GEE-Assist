"""Every algorithm the Prediction page offers, by family, with what each needs.

An algorithm serves one or more *roles*: ``regress`` (forecast values), ``classify``
(future land cover, classify the present image) or ``anomaly`` (detect anomalies). The
libraries are imported only when an algorithm is built, so a missing one only switches its
algorithms off (``available``) instead of breaking the page.

Baselines (persistence, per-pixel trend, no change, z-score) need no training and are
worked out by the service itself; they keep every other model honest: a model that cannot
beat "nothing changes" is not worth its map.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.dto.prediction_dto import ANOMALY, CHANGE, CLASSIFY, FORECAST, AlgorithmDTO

REGRESS, CLASSIFIER, OUTLIER = "regress", "classify", "anomaly"
ROLE_OF_TASK = {FORECAST: REGRESS, CHANGE: CLASSIFIER, CLASSIFY: CLASSIFIER, ANOMALY: OUTLIER}

BASELINES = {"persistence", "trend", "no_change", "zscore"}

_LIBRARY_MODULE = {"scikit-learn": "sklearn", "xgboost": "xgboost", "lightgbm": "lightgbm", "pytorch": "torch",
                   "numpy": "numpy"}
_PIP_NAME = {"scikit-learn": "scikit-learn", "xgboost": "xgboost", "lightgbm": "lightgbm", "pytorch": "torch"}


def library_available(library: str) -> bool:
    return importlib.util.find_spec(_LIBRARY_MODULE[library]) is not None


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    family: str
    roles: tuple[str, ...]
    library: str
    description: str
    build: Callable[[str, int, int], Any] | None = None   # (role, n_classes, seed) -> estimator
    scale: bool = False            # standardise the features first (distance / gradient based)
    max_train: int = 0             # most training pixels it can take in reasonable time (0: no limit)
    grid: dict[str, list] = field(default_factory=dict)  # tuning search space, by role-free name
    recommended: tuple[str, ...] = ()   # roles it is pre-selected for


# ------------------------------------------------------------- builders (imports inside)
def _sk(module: str, regressor: str | None, classifier: str | None, outlier: str | None = None, **kw):
    def build(role: str, n_classes: int, seed: int):
        mod = importlib.import_module(module)
        name = {REGRESS: regressor, CLASSIFIER: classifier, OUTLIER: outlier}[role]
        cls = getattr(mod, name)
        params = dict(kw.get("common", {}))
        params.update(kw.get(role, {}))
        if "random_state" in cls().get_params():
            params.setdefault("random_state", seed)
        return cls(**params)
    return build


def _xgb(role: str, n_classes: int, seed: int):
    import xgboost

    common = dict(n_estimators=300, max_depth=6, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9,
                  tree_method="hist", random_state=seed, n_jobs=-1, verbosity=0)
    if role == REGRESS:
        return xgboost.XGBRegressor(**common)
    return xgboost.XGBClassifier(**common, eval_metric="mlogloss")


def _lgbm(role: str, n_classes: int, seed: int):
    import lightgbm

    common = dict(n_estimators=300, learning_rate=0.08, num_leaves=63, subsample=0.9, subsample_freq=1,
                  colsample_bytree=0.9, random_state=seed, n_jobs=-1, verbose=-1)
    if role == REGRESS:
        return lightgbm.LGBMRegressor(**common)
    return lightgbm.LGBMClassifier(**common, class_weight="balanced")


def _torch(kind: str):
    def build(role: str, n_classes: int, seed: int):
        from backend.business.prediction import torch_models

        if role == REGRESS:
            return torch_models.TorchRegressor(kind=kind, seed=seed)
        if role == CLASSIFIER:
            return torch_models.TorchClassifier(kind=kind, seed=seed)
        return torch_models.TorchAutoencoder(seed=seed)
    return build


_BAL = {"classify": {"class_weight": "balanced"}}

SPECS: tuple[Spec, ...] = (
    # ---- baselines (no training)
    Spec("persistence", "Persistence (no change)", "Baselines", (REGRESS,), "numpy",
         "The future equals the present: the bar every model must beat.", recommended=(REGRESS,)),
    Spec("trend", "Per-pixel linear trend", "Baselines", (REGRESS,), "numpy",
         "A straight line through each pixel's own past, carried on to the target date.", recommended=(REGRESS,)),
    Spec("no_change", "No change (present classes)", "Baselines", (CLASSIFIER,), "numpy",
         "Every pixel keeps its present class (future land cover only)."),
    Spec("zscore", "Z-score vs own past", "Statistical", (OUTLIER,), "numpy",
         "How many standard deviations the present is from the pixel's past mean.", recommended=(OUTLIER,)),

    # ---- linear models
    Spec("linear", "Linear regression", "Linear models", (REGRESS,), "scikit-learn",
         "Ordinary least squares on the past values.", _sk("sklearn.linear_model", "LinearRegression", None),
         scale=True, recommended=(REGRESS,)),
    Spec("ridge", "Ridge regression", "Linear models", (REGRESS,), "scikit-learn",
         "Least squares with an L2 penalty: stable when past values are correlated.",
         _sk("sklearn.linear_model", "Ridge", None), scale=True, grid={"alpha": [0.01, 0.1, 1, 10, 100]}),
    Spec("lasso", "Lasso regression", "Linear models", (REGRESS,), "scikit-learn",
         "L1 penalty: keeps only the features that matter.",
         _sk("sklearn.linear_model", "Lasso", None, regress={"alpha": 0.001, "max_iter": 5000}), scale=True,
         grid={"alpha": [1e-4, 1e-3, 1e-2, 0.1]}),
    Spec("elasticnet", "Elastic net", "Linear models", (REGRESS,), "scikit-learn",
         "A blend of ridge and lasso penalties.",
         _sk("sklearn.linear_model", "ElasticNet", None, regress={"alpha": 0.001, "max_iter": 5000}), scale=True,
         grid={"alpha": [1e-4, 1e-3, 1e-2], "l1_ratio": [0.2, 0.5, 0.8]}),
    Spec("bayesian_ridge", "Bayesian ridge", "Linear models", (REGRESS,), "scikit-learn",
         "Ridge whose penalty is learnt from the data.", _sk("sklearn.linear_model", "BayesianRidge", None),
         scale=True),
    Spec("huber", "Huber regression", "Linear models", (REGRESS,), "scikit-learn",
         "Linear, but robust to outliers (clouds, sensor glitches).",
         _sk("sklearn.linear_model", "HuberRegressor", None, regress={"max_iter": 500}), scale=True,
         max_train=20_000),
    Spec("logistic", "Logistic regression", "Linear models", (CLASSIFIER,), "scikit-learn",
         "Linear class boundaries with probabilities.",
         _sk("sklearn.linear_model", None, "LogisticRegression", classify={"max_iter": 2000,
                                                                           "class_weight": "balanced"}),
         scale=True, grid={"C": [0.01, 0.1, 1, 10, 100]}, recommended=(CLASSIFIER,)),
    Spec("lda", "Linear discriminant analysis", "Probabilistic models", (CLASSIFIER,), "scikit-learn",
         "Gaussian classes with one shared covariance (a classic in remote sensing).",
         _sk("sklearn.discriminant_analysis", None, "LinearDiscriminantAnalysis")),
    Spec("qda", "Quadratic discriminant analysis", "Probabilistic models", (CLASSIFIER,), "scikit-learn",
         "Gaussian classes, each with its own covariance (maximum-likelihood classification).",
         _sk("sklearn.discriminant_analysis", None, "QuadraticDiscriminantAnalysis",
             classify={"reg_param": 0.01})),
    Spec("naive_bayes", "Gaussian naive Bayes", "Probabilistic models", (CLASSIFIER,), "scikit-learn",
         "Fast probabilistic classifier assuming independent features.",
         _sk("sklearn.naive_bayes", None, "GaussianNB")),
    Spec("gaussian_process", "Gaussian process", "Probabilistic models", (REGRESS,), "scikit-learn",
         "Kernel regression with built-in uncertainty (kriging-like); small samples only.",
         _sk("sklearn.gaussian_process", "GaussianProcessRegressor", None,
             regress={"normalize_y": True}), scale=True, max_train=1_500),

    # ---- neighbours and kernels
    Spec("knn", "k-nearest neighbours", "Neighbours & kernels", (REGRESS, CLASSIFIER), "scikit-learn",
         "Average of the most similar training pixels.",
         _sk("sklearn.neighbors", "KNeighborsRegressor", "KNeighborsClassifier", common={"n_neighbors": 7,
                                                                                         "weights": "distance"}),
         scale=True, max_train=30_000, grid={"n_neighbors": [3, 5, 7, 11, 15, 25]}),
    Spec("svm", "Support vector machine", "Neighbours & kernels", (REGRESS, CLASSIFIER), "scikit-learn",
         "RBF-kernel SVR / SVC: smooth non-linear boundaries.",
         _sk("sklearn.svm", "SVR", "SVC", classify={"probability": True, "class_weight": "balanced"}),
         scale=True, max_train=4_000, grid={"C": [0.1, 1, 10, 100], "gamma": ["scale", 0.01, 0.1, 1]}),

    # ---- trees
    Spec("decision_tree", "Decision tree", "Trees", (REGRESS, CLASSIFIER), "scikit-learn",
         "One tree of if-then splits: easy to read, quick to overfit.",
         _sk("sklearn.tree", "DecisionTreeRegressor", "DecisionTreeClassifier", common={"min_samples_leaf": 5},
             **_BAL), grid={"max_depth": [4, 8, 12, 20, None], "min_samples_leaf": [1, 5, 20]}),
    Spec("random_forest", "Random forest", "Tree ensembles", (REGRESS, CLASSIFIER), "scikit-learn",
         "Hundreds of decorrelated trees averaged: the remote-sensing workhorse.",
         _sk("sklearn.ensemble", "RandomForestRegressor", "RandomForestClassifier",
             common={"n_estimators": 200, "n_jobs": -1, "min_samples_leaf": 2}, **_BAL),
         grid={"n_estimators": [100, 200, 400], "max_depth": [None, 12, 24], "max_features": ["sqrt", 0.5, 1.0]},
         recommended=(REGRESS, CLASSIFIER)),
    Spec("extra_trees", "Extra trees", "Tree ensembles", (REGRESS, CLASSIFIER), "scikit-learn",
         "Extremely randomised trees: faster than a forest, often as good.",
         _sk("sklearn.ensemble", "ExtraTreesRegressor", "ExtraTreesClassifier",
             common={"n_estimators": 200, "n_jobs": -1, "min_samples_leaf": 2}, **_BAL),
         grid={"n_estimators": [100, 200, 400], "max_features": ["sqrt", 0.5, 1.0]}),
    Spec("gradient_boosting", "Gradient boosting", "Boosting", (REGRESS, CLASSIFIER), "scikit-learn",
         "Histogram gradient boosting: trees fitted to the previous trees' errors.",
         _sk("sklearn.ensemble", "HistGradientBoostingRegressor", "HistGradientBoostingClassifier",
             common={"max_iter": 300, "learning_rate": 0.08}, **_BAL),
         grid={"learning_rate": [0.03, 0.08, 0.2], "max_leaf_nodes": [15, 31, 63], "max_iter": [200, 400]},
         recommended=(REGRESS, CLASSIFIER)),
    Spec("adaboost", "AdaBoost", "Boosting", (REGRESS, CLASSIFIER), "scikit-learn",
         "Boosting that re-weights the pixels the last trees got wrong.",
         _sk("sklearn.ensemble", "AdaBoostRegressor", "AdaBoostClassifier", common={"n_estimators": 150}),
         grid={"n_estimators": [50, 150, 300], "learning_rate": [0.05, 0.3, 1.0]}),
    Spec("xgboost", "XGBoost", "Boosting", (REGRESS, CLASSIFIER), "xgboost",
         "Regularised gradient boosting; often the most accurate on pixel data.", _xgb,
         grid={"max_depth": [4, 6, 8], "learning_rate": [0.03, 0.08, 0.2], "n_estimators": [200, 400]},
         recommended=(REGRESS, CLASSIFIER)),
    Spec("lightgbm", "LightGBM", "Boosting", (REGRESS, CLASSIFIER), "lightgbm",
         "Leaf-wise gradient boosting: very fast on many pixels.", _lgbm,
         grid={"num_leaves": [31, 63, 127], "learning_rate": [0.03, 0.08, 0.2], "n_estimators": [200, 400]}),

    # ---- neural networks
    Spec("mlp", "Neural network (MLP)", "Neural networks", (REGRESS, CLASSIFIER), "scikit-learn",
         "A multi-layer perceptron (scikit-learn), early stopping on a held-out part.",
         _sk("sklearn.neural_network", "MLPRegressor", "MLPClassifier",
             common={"hidden_layer_sizes": (64, 32), "early_stopping": True, "max_iter": 1500}),
         scale=True, grid={"hidden_layer_sizes": [(32,), (64, 32), (128, 64)], "alpha": [1e-5, 1e-4, 1e-3]}),
    Spec("torch_mlp", "Deep neural network", "Deep learning", (REGRESS, CLASSIFIER), "pytorch",
         "A deeper PyTorch network (3 hidden layers, dropout, batch norm).", _torch("mlp"), scale=True),
    Spec("torch_lstm", "LSTM (recurrent)", "Deep learning", (REGRESS, CLASSIFIER), "pytorch",
         "Long short-term memory network reading the past dates in order.", _torch("lstm"), scale=True),
    Spec("torch_tcn", "Temporal CNN", "Deep learning", (REGRESS, CLASSIFIER), "pytorch",
         "1-D convolutions over the time series (a temporal convolutional network).", _torch("tcn"), scale=True),

    # ---- anomaly detectors
    Spec("isolation_forest", "Isolation forest", "Outlier detection", (OUTLIER,), "scikit-learn",
         "Unusual pixels are isolated by fewer random splits.",
         _sk("sklearn.ensemble", None, None, "IsolationForest", anomaly={"n_estimators": 200, "n_jobs": -1}),
         recommended=(OUTLIER,)),
    Spec("lof", "Local outlier factor", "Outlier detection", (OUTLIER,), "scikit-learn",
         "Pixels in sparser neighbourhoods than their neighbours are outliers.",
         _sk("sklearn.neighbors", None, None, "LocalOutlierFactor", anomaly={"novelty": True, "n_neighbors": 30}),
         scale=True, max_train=20_000),
    Spec("one_class_svm", "One-class SVM", "Outlier detection", (OUTLIER,), "scikit-learn",
         "A boundary around normal pixels; whatever falls outside is anomalous.",
         _sk("sklearn.svm", None, None, "OneClassSVM", anomaly={"nu": 0.05, "gamma": "scale"}),
         scale=True, max_train=5_000),
    Spec("elliptic_envelope", "Elliptic envelope", "Outlier detection", (OUTLIER,), "scikit-learn",
         "A robust Gaussian fit (minimum covariance determinant); far pixels are outliers.",
         _sk("sklearn.covariance", None, None, "EllipticEnvelope", anomaly={"support_fraction": 0.9}),
         scale=True, max_train=20_000),
    Spec("autoencoder", "Autoencoder", "Deep learning", (OUTLIER,), "pytorch",
         "A network that learns to rebuild normal pixels; a large rebuild error means anomaly.",
         _torch("auto"), scale=True, recommended=(OUTLIER,)),
)

SPEC_BY_KEY = {spec.key: spec for spec in SPECS}


def specs_for(task: str) -> list[Spec]:
    role = ROLE_OF_TASK[task]
    specs = [spec for spec in SPECS if role in spec.roles]
    if task == CLASSIFY:   # no time series here: "no change" and the sequence networks do not apply
        specs = [spec for spec in specs if spec.key not in ("no_change", "torch_lstm", "torch_tcn")]
    if task != CHANGE:
        specs = [spec for spec in specs if spec.key != "no_change"]
    return specs


def algorithm_dtos(task: str) -> list[AlgorithmDTO]:
    role = ROLE_OF_TASK[task]
    out = []
    for spec in specs_for(task):
        available = library_available(spec.library)
        out.append(AlgorithmDTO(
            key=spec.key, label=spec.label, family=spec.family, tasks=tuple(
                t for t, r in ROLE_OF_TASK.items() if r in spec.roles), library=spec.library,
            available=available, description=spec.description, recommended=role in spec.recommended,
            missing="" if available else f"Needs {spec.library} (pip install {_PIP_NAME.get(spec.library, spec.library)})",
        ))
    return out
