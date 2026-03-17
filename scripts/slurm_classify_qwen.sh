#!/bin/bash
#SBATCH --job-name=classify-qwen
#SBATCH --account=def-aengusb_gpu
#SBATCH --time=6:00:00
#SBATCH --mem=80G
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:h100:1
#SBATCH --partition=gpubase_bygpu_b2
#SBATCH --output=/scratch/aengusb/ai_news_audit/logs/classify-qwen-%j.out
#SBATCH --error=/scratch/aengusb/ai_news_audit/logs/classify-qwen-%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=aengus.bridgman@mcgill.ca

set -euo pipefail

SIF=/scratch/aengusb/apptainer/vllm-qwen3_5.sif
MODEL="Qwen/Qwen3.5-35B-A3B-FP8"
PORT=8192
SCRATCH=/scratch/aengusb/ai_news_audit

mkdir -p $SCRATCH/logs $SCRATCH/data

echo "=== classify-qwen job $SLURM_JOB_ID ==="
echo "Node: $(hostname)"
echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
date

# ── 1. Start vLLM server inside Apptainer container ──
module load apptainer

apptainer run --nv \
    --bind /scratch/aengusb:/scratch/aengusb \
    --env HF_HOME=/scratch/aengusb/hf_cache \
    --env HF_HUB_OFFLINE=1 \
    $SIF \
    --model "$MODEL" \
    --port $PORT \
    --tensor-parallel-size 1 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.90 \
    --no-enable-prefix-caching \
    --enforce-eager \
    --trust-remote-code \
    --limit-mm-per-prompt.image 0 \
    --limit-mm-per-prompt.video 0 \
    --disable-log-requests \
    &

VLLM_PID=$!
echo "vLLM PID: $VLLM_PID"

# ── 2. Wait for server ready (model load ~3 min) ──
echo "Waiting for vLLM server on port $PORT..."
for i in $(seq 1 120); do
    if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
        echo "  Server ready after $((i*5))s"
        break
    fi
    if ! kill -0 $VLLM_PID 2>/dev/null; then
        echo "  ERROR: vLLM server died. Check logs."
        exit 1
    fi
    sleep 5
done

if ! curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
    echo "  ERROR: Server failed to start within 10 min"
    kill $VLLM_PID 2>/dev/null
    exit 1
fi

# ── 3. Run classify script (host Python + openai) ──
module load python/3.11.5
source ~/venv_vllm/bin/activate

python -u $SCRATCH/scripts/classify_qwen.py \
    --port $PORT \
    --model "$MODEL" \
    --input  $SCRATCH/data/track2_responses.jsonl \
    --output $SCRATCH/data/track2_coded_qwen.jsonl \
    --workers 6 \
    --resume

echo "=== Classification done ==="
date

# ── 4. Shut down vLLM ──
kill $VLLM_PID 2>/dev/null
wait $VLLM_PID 2>/dev/null || true
echo "vLLM server stopped."
