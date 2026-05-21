#═════════════════════| INSTALLATIONS |═════════════════════════════════
import getpass
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from venv_manager import install_deps
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
packages = [
    "ragas>=0.2.0", "chromadb>=0.5.0","openai>=1.30.0",
    "langchain-openai>=0.1.0", "datasets>=2.14.0", "tiktoken", "pandas", "matplotlib"
]
install_deps(packages)
import os
import warnings
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore')
api_key= getpass.getpass("OPENAI_API_KEY: ")
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI

# RAGAS v0.2+ uses class-based metrics and EvaluationDataset
from ragas import evaluate, EvaluationDataset
from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import (
    Faithfulness,
    AnswerRelevancy,
    LLMContextPrecisionWithReference,
    LLMContextRecall,
    AnswerCorrectness,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

print('All imports OK')