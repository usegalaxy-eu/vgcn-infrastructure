#!/bin/bash
if (( $# != 5 )); then
    echo "Usage:"
    echo
    echo "  $0 <training-identifier> <vm-size> <vm-count> <start> <end> [--donotautocommitpush]"
    echo
    exit 1;
fi

training_identifier=$(echo "$1" | tr '[:upper:]' '[:lower:]')
vm_size=${2:-c.c10m55}
vm_count=${3:-1}
start=$4
end=$5
autopush=1
if [[ "$6" == "--donotautocommitpush" ]]; then
	autopush=0
fi

short=$(echo "$training_identifier" | cut -c1-4)

output="instance_training-${training_identifier}.tf"

cat >> resources.yaml <<-EOF
    training-${short}:
        count: ${vm_count}
        flavor: ${vm_size}
        start: ${start}
        end: ${end}
        group: training-${training_identifier}
EOF

if (( autopush == 1 )); then
	git add resources.yaml
	git commit -m 'New training'
	git push
fi

vm_cpu=$(echo $vm_size | sed 's/[^0-9]/ /g' | awk '{print $1}')
vm_mem=$(echo $vm_size | sed 's/[^0-9]/ /g' | awk '{print $2}')

echo " - ${training_identifier}" >> ../infrastructure-playbook/group_vars/tiaas.yml

if (( autopush == 1 )); then
	cd ../infrastructure-playbook/
	git add group_vars/tiaas.yml
	git commit -m 'New training'
	git push
	cd -
fi

ts_end=$(date -d "$end 23:59" +%s)
ts_stt=$(date -d "$start 00:00" +%s)
vm_seconds=$(( ts_end - ts_stt ))
price=$(python cost.py $vm_cpu $vm_mem $vm_seconds | head -n 1)
machines=$(python cost.py $vm_cpu $vm_mem $vm_seconds | tail -n 1)
aws_id=$(echo $machines | sed "s/'/\"/g" | jq .name -r)
price=$(echo "$price * $vm_count" | bc -l)
yourname=$(git config --global --get user.name)

printf "
Subject: UseGalaxy.eu TIaaS Request: Approved

Hello,

Based on your requested training we have allocated ${vm_count} server(s), each with ${vm_cpu} Cores and ${vm_mem} GB of RAM. This should be sufficient for your purposes. If you find that it is not, please contact us and we can update that at any time. On the day of your training, please ask your users to go to the following URL:

https://usegalaxy.eu/join-training/${1}

They will be added to the training group and put into a private queue which should be a bit faster than our regular queue. Your training queue will be available from ${start} to ${end}.


*Queue Status*:
If you find yourself wondering where your students are during the training, you can use the new queue status page to see which jobs are being run by people in your training: https://usegalaxy.eu/join-training/${1}/status

*AWS Estimate*:
If you wanted to run a similar training on AWS, we estimate that for ${vm_count} ${aws_id} machines, it would cost ${price}USD

Please let us know if you have any questions!

Regards,
${yourname}

--
${yourname}

UseGalaxy.eu
Bioinformatics Group
Department of Computer Science
Albert-Ludwigs-University Freiburg
Georges-Köhler-Allee 106
79110 Freiburg, Germany
"
