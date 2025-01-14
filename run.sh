#!/bin/bash

# Start scrcpy in the background
scrcpy -d &
SCRCPY_PID=$!

# Wait a bit to ensure scrcpy is initialised
sleep 2

# Start the Python script
python feed_monitor.py

# Kill scrcpy after the Python script finishes
kill $SCRCPY_PID