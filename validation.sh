# Validation functions for add-training.sh

show_help() {
    echo "Usage:"
    echo
    echo "Interactive Mode:"
    echo "  $0 -i <training-identifier> <vm-size (e.g. c1.c120m205d50)> <vm-count> <\"trainer name\"> <\"trainer email\"> [--donotautocommitpush]"
    echo
    echo "Non-Interactive Mode:"
    echo "  $0 <training-identifier> <vm-size (e.g. c1.c120m205d50)> <vm-count> <start in YYYY-MM-DD> <end in YYYY-MM-DD> <\"trainer name\"> <\"trainer email\"> [--donotautocommitpush]"
    echo
    exit 0
}

validate_date() {
    local current_timezone=$(date +%z)
    local current_time=$(date +%H:%M:%S)
    local input_date="$1"
    local date_training="$input_date $current_time $current_timezone"
    echo "date_training: $date_training"
    # Check if the date is in YYYY-MM-DD HH:MM:SS +ZZZZ format
    echo "Checking date format for: $date_training"
    if ! [[ "$date_training" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\ [+-][0-9]{4}$ ]]; then
        echo "Error: '$date_training' is not in YYYY-MM-DD HH:MM:SS +0000 format"
        return 1
    fi

    # Validate actual date (catches things like 2023-02-30)
    if ! date -d "$date_training" >/dev/null 2>&1; then
        echo "Error: '$date_training' is not a valid date"
        return 1
    fi

    # Compare input date (with timezone and current time) to current date (with timezone) in epoch seconds
    local input_epoch=$(date -d "$date_training" +%s)
    local now_epoch=$(date +%s)
    echo "Input epoch: $input_epoch"
    echo "Now epoch: $now_epoch"
    if [ "$input_epoch" -lt "$now_epoch" ]; then
        echo "Error: '$date_training' is in the past"
        return 1
    fi

    return 0
}

check_conflicts() {
    python check_conflicts.py
    if [ $? -ne 0 ]; then
        echo "Conflict detected in resources.yaml. Aborting."
        # Remove the last added training entry from resources.yaml
        head -n -$number_of_lines resources.yaml > tmp && mv tmp resources.yaml
        exit 1
    fi
}
