#!/bin/bash

source validation.sh

# Forcing buffered output to stderr in interactive mode
say() { echo "$@" >&2; }

# Help option
if [[ "$1" == "-h" ]]; then
    show_help
fi

if [ "$1" == "--interactive" ] || [ "$1" == "-i" ]; then
	# Interactive mode: multiple trainings
	# add-training.sh -i($1) <training-identifier>($2) <vm-size>($3) <vm-count>($4) 
	# <trainer name>($5) <trainer-email>($6) --donotautocommitpush($7)
	if ([ $# -gt 7 ] || [ $# -lt 6 ]); then
		echo "Usage:"
		echo
		echo "  $0 -i <training-identifier> <vm-size (e.g. c1.c120m205d50)> <vm-count> <"trainer name"> <"trainer email"> [--donotautocommitpush]"
		echo
		exit 1;
	fi
	training_identifier=$(echo "$2" | tr '[:upper:]' '[:lower:]')
	vm_size=${3:-c.c10m55}
	vm_count=${4:-1}
	trainer_name=$5
	trainer_mail_address=$6
	autopush=1
	if [[ "$7" == "--donotautocommitpush" ]]; then
		autopush=0
	fi

	short=$(echo "$training_identifier" | cut -c1-4)
    
	# Interactive mode - prompt for multiple date pairs
	echo "Interactive mode: Enter date pairs (press Enter on empty line to finish)"
	dates=()
	while true; do
		# Start date
		read -p "Enter start date (YYYY-MM-DD) or press Enter to finish: " start
		[ -z "$start" ] && break
		say "Validating start date: $start" >&2
		if validate_date "$start"; then
			say "Start date '$start' is valid."
		else
			say "Invalid start date. Please try again." >&2
			continue
		fi
		# End date
		read -p "Enter end date (YYYY-MM-DD): " end
		if validate_date "$end"; then
			say "Start date '$end' is valid."
		else
			say "Invalid end date. Please try again."
			continue
		fi
		dates+=("$start,$end")
	done
	# Process the dates
	array_length=${#dates[@]}
	number_of_lines=$((array_length * 6))
for date_pair in "${dates[@]}"; do
    IFS=',' read -r start end <<< "$date_pair"
	randnum=$(shuf -i 1000-9999 -n 1)
	# Adding the training to resources.yaml
	cat >> resources.yaml <<-EOF
	  training-${short}${randnum}:
	    count: ${vm_count}
	    flavor: ${vm_size}
	    start: ${start}
	    end: ${end}
	    group: training-${training_identifier}
	EOF
done
	# Check for conflicts
	check_conflicts
	# Create the mail draft for Thunderbird. However, Thunderbird is not always the standard mail client and it is not clear how Thunderbird was configured on the target system (sandboxed vs. system install and which profile to use etc.).
	#flatpak run net.thunderbird.Thunderbird -P default-esr -compose "to='$6',cc='galaxy-ops@informatik.uni-freiburg.de',subject='$subject',body='$body'"
	# Create a multi-platform mail draft independent of a specific mail client
	source mail_template_eml.sh
else
	# Non-interactive mode for single training - expect at least seven arguments
	# add-training.sh <training-identifier>($1) c1.c120m205d50($2) <anzahl der vms>($3) yyyy-mm-dd($4) (start) 
	# yyyy-mm-dd($5) (end) <"trainer name">($6) <"trainer-email">($7) --donotautocommitpush ($8))
	if ([ $# -lt 7 ]); then
		echo "Usage:"
		echo
		echo "  $0 <training-identifier> <vm-size (e.g. c1.c120m205d50)> <vm-count> <start in YYYY-mm-dd> <end in YYYY-mm-dd> <"trainer name"> <"trainer email"> [--donotautocommitpush]"
		echo
		exit 1;
	fi
	training_identifier=$(echo "$1" | tr '[:upper:]' '[:lower:]')
	vm_size=${2:-c.c10m55}
	vm_count=${3:-1}
	start=$4
	end=$5
	trainer_name=$6
	trainer_mail_address=$7
	autopush=1
	if [[ "$8" == "--donotautocommitpush" ]]; then
		autopush=0
	fi

	short=$(echo "$training_identifier" | cut -c1-4)

	# Validate dates
	while true; do
		if validate_date "$start"; then
			echo "Start date '$start' is valid."
		else
			echo "Invalid start date. Please try again."
			exit 1
		fi
		if validate_date "$end"; then
			echo "End date '$end' is valid."
			break
		else
			echo "Invalid end date. Please try again."
			exit 1
		fi
	done
   # Adding the training to resources.yaml
   	randnum=$(shuf -i 1000-9999 -n 1)
	cat >> resources.yaml <<-EOF
	  training-${short}${randnum}:
	    count: ${vm_count}
	    flavor: ${vm_size}
	    start: ${start}
	    end: ${end}
	    group: training-${training_identifier}
	EOF
	# Creating the mail draft
	number_of_lines=6
	check_conflicts
	source mail_template_eml.sh
fi
