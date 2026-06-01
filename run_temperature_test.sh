#!/bin/bash

echo "🧪 Running Nirvana Nuts Temperature Test"
echo "========================================="

# Activate conda environment
conda activate tflow

# Run temperature test
echo "Generating tweets at different temperatures..."
python test_temperatures.py

# Run comparison analysis
echo ""
echo "Running comparison analysis..."
python compare_temperatures.py

echo ""
echo "✅ Temperature test complete!"
echo "Check the generated JSON file for detailed results"
