adb tcpip 5555 && timeout=30 && start=$(date +%s) && while true; do
  ip=$(adb shell ip -f inet addr show wlan0 | grep inet | awk '{print $2}' | cut -d/ -f1)
  if [ -n "$ip" ]; then
    adb connect $ip:5555 && echo "Connected successfully!" && break
  else
    echo "Waiting for IP address..."
  fi
  sleep 1
  now=$(date +%s)
  if (( now - start >= timeout )); then
    echo "Timeout reached. Failed to connect."
    break
  fi
done