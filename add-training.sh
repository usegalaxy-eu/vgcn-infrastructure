#!/bin/bash
if (( $# != 5 )); then
    echo "Usage:"
    echo
    echo "  $0 <training-identifier> <vm-size> <vm-count> <start> <end>"
    echo
    exit 1;
fi

training_identifier=$(echo "$1" | tr '[:upper:]' '[:lower:]')
vm_size=${2:-c.c10m55}
vm_count=${3:-1}
start=$4
end=$5

output="instance_training-${training_identifier}.tf"

cat >> resources.yaml <<-EOF
    training-${training_identifier}:
        count: ${vm_count}
        flavor: ${vm_size}
        start: ${start}
        end: ${end}
EOF

vm_cpu=$(echo $vm_size | sed 's/[^0-9]/ /g' | awk '{print $1}')
vm_mem=$(echo $vm_size | sed 's/[^0-9]/ /g' | awk '{print $2}')


echo "
Subject: UseGalaxy.eu TIaaS Request: Approved

Hello,

Based on your requested training we have allocated ${vm_count} server(s), each with ${vm_cpu} Cores and ${vm_mem} GB of RAM. This should be sufficient for your purposes. If you find that it is not, please contact us and we can update that at any time.

On the day of your training, please ask your users to go to the following URL: https://usegalaxy.eu/join-training/${1}

They will be added to the training group and put into a private queue which should be a bit faster than our regular queue.

Your training queue will be available from ${start} to ${end}

Please let us know if you have any questions!

Regards,
Helena

--
Helena Rasche

UseGalaxy.eu Server Administrator
Bioinformatics Group
Department of Computer Science
Albert-Ludwigs-University Freiburg
Georges-Köhler-Allee 106
79110 Freiburg, Germany
"
