import sys


ec2 = {
    'CVRPW534R69RUEMP': {'name': 't3.nano', 'mem': 0.5, 'price': 0.006, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'BXS2CDUKEC83Q4SH': {'name': 'm5.xlarge', 'mem': 16.0, 'price': 0.23, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon Platinum 8175'},
    '5ZJ896MTVHB5JV5Y': {'name': 't2.medium', 'mem': 4.0, 'price': 0.0536, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Family'},
    'GHQYBQHT7SSW3G2C': {'name': 't2.large', 'mem': 8.0, 'price': 0.1072, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Family'},
    '8KTQAHWA58GUHDGC': {'name': 'm3.large', 'mem': 7.5, 'price': 0.158, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    'FVQQQM6YZMWR2CH8': {'name': 'm5d.12xlarge', 'mem': 192.0, 'price': 3.264, 'priceunit': 'Hrs', 'vcpus': 48, 'cpu': 'Intel Xeon Platinum 8175'},
    'XWVCP8TVZ3EZXHJT': {'name': 'm4.10xlarge', 'mem': 160.0, 'price': 2.4, 'priceunit': 'Hrs', 'vcpus': 40, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    '4K2RDTDA5QDSVF79': {'name': 'm5d.2xlarge', 'mem': 32.0, 'price': 0.544, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon Platinum 8175'},
    'WVY4KGHQEHERBSCH': {'name': 'm5d.4xlarge', 'mem': 64.0, 'price': 1.088, 'priceunit': 'Hrs', 'vcpus': 16, 'cpu': 'Intel Xeon Platinum 8175'},
    'EF7GKFKJ3Y5DM7E9': {'name': 'm4.xlarge', 'mem': 16.0, 'price': 0.24, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    'EJKFPM8NFNPPN8K3': {'name': 't3.xlarge', 'mem': 16.0, 'price': 0.192, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'VKC9JFWDJCMTC9PM': {'name': 'm5d.metal', 'mem': 384.0, 'price': 6.528, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    'KZ25CYAW7ZZ6SN5U': {'name': 't3.xlarge', 'mem': 16.0, 'price': 0.192, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    '6GR6HHW9M8KXFW8G': {'name': 't3.large', 'mem': 8.0, 'price': 0.096, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'MWZ782FC8DW7J99A': {'name': 't2.small', 'mem': 2.0, 'price': 0.0268, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon Family'},
    'J49TZ5ZB5Y6C86JU': {'name': 't3.nano', 'mem': 0.5, 'price': 0.006, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'UZVS6KCHDUP826JV': {'name': 'm5d.12xlarge', 'mem': 192.0, 'price': 3.264, 'priceunit': 'Hrs', 'vcpus': 48, 'cpu': 'Intel Xeon Platinum 8175'},
    'MU5U93W873MZ8Z5D': {'name': 'm5.metal', 'mem': 384.0, 'price': 5.52, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    'DWFM7CT7HR9PKX7G': {'name': 'm5d.2xlarge', 'mem': 32.0, 'price': 0.544, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon Platinum 8175'},
    'H6ECMC3MHDHUV96Z': {'name': 't3.medium', 'mem': 4.0, 'price': 0.048, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'Q6FFSFPJYR84UFKC': {'name': 't2.xlarge', 'mem': 16.0, 'price': 0.2144, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon Family'},
    'WDV8EGFDZABESVSJ': {'name': 't2.micro', 'mem': 1.0, 'price': 0.0134, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon Family'},
    '5ZZCF2WTD3M2NVHT': {'name': 'm3.xlarge', 'mem': 15.0, 'price': 0.315, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    '8SQHN34JP8S4C4GV': {'name': 't2.xlarge', 'mem': 16.0, 'price': 0.2144, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon Family'},
    'ZWPFR7HFRCGJ2QTR': {'name': 'm4.10xlarge', 'mem': 160.0, 'price': 2.4, 'priceunit': 'Hrs', 'vcpus': 40, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    '79M3634SCM5Q9T3J': {'name': 'm5.2xlarge', 'mem': 32.0, 'price': 0.46, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon Platinum 8175'},
    '7SN7STWTVJW3W2G9': {'name': 'm5d.xlarge', 'mem': 16.0, 'price': 0.272, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon Platinum 8175'},
    'N5D4RSFRNZ3SRTJ3': {'name': 'm5.2xlarge', 'mem': 32.0, 'price': 0.46, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon Platinum 8175'},
    '8KSV5UWZA8Q5NDMM': {'name': 'm5.large', 'mem': 8.0, 'price': 0.115, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Platinum 8175'},
    'CDQ3VSAVRNG39R6V': {'name': 'm4.2xlarge', 'mem': 32.0, 'price': 0.48, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    'ASEABRAPY52SVJQW': {'name': 'm5.xlarge', 'mem': 16.0, 'price': 0.23, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon Platinum 8175'},
    'CU49Z77S6UH36JXW': {'name': 't2.small', 'mem': 2.0, 'price': 0.0268, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon Family'},
    'BQGVWHYQ8YK6UNK7': {'name': 't3.2xlarge', 'mem': 32.0, 'price': 0.384, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'QJ82YTRR8GFNUS8T': {'name': 'm4.16xlarge', 'mem': 256.0, 'price': 3.84, 'priceunit': 'Hrs', 'vcpus': 64, 'cpu': 'Intel Xeon E5-2686 v4 (Broadwell)'},
    'JGXEWM5NJCZJPHGG': {'name': 'm4.4xlarge', 'mem': 64.0, 'price': 0.96, 'priceunit': 'Hrs', 'vcpus': 16, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    'GAZSSNJQ6FMMHE3Z': {'name': 't2.nano', 'mem': 0.5, 'price': 0.0067, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon Family'},
    'VDE8R7MCSGDRYAK3': {'name': 'm5d.metal', 'mem': 384.0, 'price': 6.528, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    '7EFZWDA5CSAB85BF': {'name': 't2.2xlarge', 'mem': 32.0, 'price': 0.4288, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon Family'},
    '9UR7CWCC3D8XJM5D': {'name': 'm5.metal', 'mem': 384.0, 'price': 5.52, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    'PXVP8BEWB9MCWMNR': {'name': 't3.micro', 'mem': 1.0, 'price': 0.012, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'R2292NDJY8MEG6E9': {'name': 'm4.xlarge', 'mem': 16.0, 'price': 0.24, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    'WDVKBS7C22UHKEXB': {'name': 'm5.4xlarge', 'mem': 64.0, 'price': 0.92, 'priceunit': 'Hrs', 'vcpus': 16, 'cpu': 'Intel Xeon Platinum 8175'},
    '85ZP32Z5B2G2SYVH': {'name': 'm5d.24xlarge', 'mem': 384.0, 'price': 6.528, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    '5P7657GQ9EZ2Z4ZY': {'name': 't2.medium', 'mem': 4.0, 'price': 0.0536, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Family'},
    'CNP4PV4Y2J8YZVAR': {'name': 'm3.2xlarge', 'mem': 30.0, 'price': 0.632, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    'XGAATXHUHNWXTMMR': {'name': 't3.small', 'mem': 2.0, 'price': 0.024, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'ADZF37JDQVT3WGPY': {'name': 'm5d.4xlarge', 'mem': 64.0, 'price': 1.088, 'priceunit': 'Hrs', 'vcpus': 16, 'cpu': 'Intel Xeon Platinum 8175'},
    'T9GCN3NZ9U6N5BGN': {'name': 't2.micro', 'mem': 1.0, 'price': 0.0134, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon Family'},
    'MB2NWM9D8ZZSBHR4': {'name': 'm4.16xlarge', 'mem': 256.0, 'price': 3.84, 'priceunit': 'Hrs', 'vcpus': 64, 'cpu': 'Intel Xeon E5-2686 v4 (Broadwell)'},
    '7W6DNQ55YG9FCPXZ': {'name': 't2.large', 'mem': 8.0, 'price': 0.1072, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Family'},
    'A65VEHYMUBAYJ5QH': {'name': 'm5.12xlarge', 'mem': 192.0, 'price': 2.76, 'priceunit': 'Hrs', 'vcpus': 48, 'cpu': 'Intel Xeon Platinum 8175'},
    'GAE4UTCSMAJWBBFJ': {'name': 'm3.2xlarge', 'mem': 30.0, 'price': 0.632, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    'A4PSTURH2MNXCCEY': {'name': 'm5.24xlarge', 'mem': 384.0, 'price': 5.52, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    'FJGAN929UK7ZM2ZP': {'name': 'm5d.large', 'mem': 8.0, 'price': 0.136, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Platinum 8175'},
    '9F7RB34BNUJTPE58': {'name': 'm5d.large', 'mem': 8.0, 'price': 0.136, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Platinum 8175'},
    'Z2K4FMUDPSU2Y95K': {'name': 'm5d.24xlarge', 'mem': 384.0, 'price': 6.528, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    'BMXENRM9BM54QBEV': {'name': 'm5.24xlarge', 'mem': 384.0, 'price': 5.52, 'priceunit': 'Hrs', 'vcpus': 96, 'cpu': 'Intel Xeon Platinum 8175'},
    '7X63DAK78VTPCW8F': {'name': 't3.2xlarge', 'mem': 32.0, 'price': 0.384, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'GDZZPNEEZXAN7X9J': {'name': 'm3.medium', 'mem': 3.75, 'price': 0.079, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    '5FF8EWYB29V3BMFR': {'name': 'm4.2xlarge', 'mem': 32.0, 'price': 0.48, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    'JSXG89ERGHPGMPFM': {'name': 'm5.large', 'mem': 8.0, 'price': 0.115, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon Platinum 8175'},
    'QR7F3KDAWU8AH7GS': {'name': 'm5.4xlarge', 'mem': 64.0, 'price': 0.92, 'priceunit': 'Hrs', 'vcpus': 16, 'cpu': 'Intel Xeon Platinum 8175'},
    'S9TWRX7CSGVGFTUF': {'name': 'm3.large', 'mem': 7.5, 'price': 0.158, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    'NM35WHNW4RD6ZH4A': {'name': 't3.small', 'mem': 2.0, 'price': 0.024, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'V9KJ6N2U7KUVD6B4': {'name': 'm3.medium', 'mem': 3.75, 'price': 0.079, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'},
    'QDVJP86F8XHGBSMH': {'name': 'm4.4xlarge', 'mem': 64.0, 'price': 0.96, 'priceunit': 'Hrs', 'vcpus': 16, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    '9PBREHF5JRKB6RBE': {'name': 't3.micro', 'mem': 1.0, 'price': 0.012, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'RKVEJUJU9XMQKRKT': {'name': 'm5d.xlarge', 'mem': 16.0, 'price': 0.272, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon Platinum 8175'},
    'RP7JF6K2NBW9Y4SJ': {'name': 't3.medium', 'mem': 4.0, 'price': 0.048, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'QJXTGC5R5C4GXQJZ': {'name': 't2.2xlarge', 'mem': 32.0, 'price': 0.4288, 'priceunit': 'Hrs', 'vcpus': 8, 'cpu': 'Intel Xeon Family'},
    'XH9A78C54UHFZGRU': {'name': 'm4.large', 'mem': 8.0, 'price': 0.12, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    '6PSHDB8D545JMBBD': {'name': 't2.nano', 'mem': 0.5, 'price': 0.0067, 'priceunit': 'Hrs', 'vcpus': 1, 'cpu': 'Intel Xeon Family'},
    'ABFDCPB959KUGRH8': {'name': 'm4.large', 'mem': 8.0, 'price': 0.12, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Xeon E5-2676 v3 (Haswell)'},
    '94CQG9X2X6WQEE35': {'name': 'm5.12xlarge', 'mem': 192.0, 'price': 2.76, 'priceunit': 'Hrs', 'vcpus': 48, 'cpu': 'Intel Xeon Platinum 8175'},
    '5Y4HW2NEZ28KD55H': {'name': 't3.large', 'mem': 8.0, 'price': 0.096, 'priceunit': 'Hrs', 'vcpus': 2, 'cpu': 'Intel Skylake E5 2686 v5 (2.5 GHz)'},
    'FD8FGSQDGNM69YJF': {'name': 'm3.xlarge', 'mem': 15.0, 'price': 0.315, 'priceunit': 'Hrs', 'vcpus': 4, 'cpu': 'Intel Xeon E5-2670 v2 (Ivy Bridge/Sandy Bridge)'}
}


if len(sys.argv) != 4:
    print("vcpus, mem, seconds")
    sys.exit()

vcpus, mem, seconds = map(float, sys.argv[1:4])

for sku, data in sorted(ec2.items(), key=lambda x: (x[1]['mem'], x[1]['vcpus'])):
    if data['mem'] >= mem and data['vcpus'] >= vcpus:

        if data['priceunit'] != 'Hrs':
            raise Exception()

        print(seconds * data['price'] / 3600) # price per second
        print(data)
        break
