
def find_fastq(wildcards):
    path = '0000_raws/0100_reads/genomic/'
    result = [y for x in os.walk(path) for y in glob(os.path.join(x[0], '*.fastq.gz')) if "/" + wildcards.sample +"_" in y]
    assert len(result) == 2, print(result)
    return result


def all_dones(wildcards):
    path = '0000_raws/0100_reads/genomic/'
    result = [pjoin("1000_processed_reads/","_".join(s.split("_")[:-4]),"done") for s in os.listdir(path) if s.endswith(".fastq.gz")  ]
    return list(set(result))


rule fastqc:
    input :  find_fastq
    output : "1000_processed_reads/{sample}/reads/fastqc"
    threads : THREADS
    shell:
        """
        fastqc -t {threads} -o {output} {input}
        """


rule trimmomatic:
    """ QCing and cleaning reads """
    params : java_cmd = config['trimmomatic']['java_cmd'],
             jar_file = config['trimmomatic']['jar_file'],
             mem = config['trimmomatic']['java_vm_mem']
             options = config['trimmomatic']['options'],
             processing_options = config['trimmomatic']['processing_options'],
             temp_folder = config['general']['temp_dir']
    input :  find_fastq
    output : read1 = "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_1P.fastq.gz",
             read2 = "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_2P.fastq.gz",
             read1U = "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_1U.fastq.gz",
             read2U = "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_2U.fastq.gz",
    threads : config['general']['threads']
    log : "1000_processed_reads/{sample}/reads/trimmomatic/{sample}.log"
    shell:
        """
        unpigz -c `echo {input} | tr ' ' '\n' | grep "_R1_"`  >  {params.temp_folder}/temp_R1.fastq
        unpigz -c `echo {input} | tr ' ' '\n' | grep "_R2_"` >  {params.temp_folder}/temp_R2.fastq

        {params.java_cmd} -Xmx{params.mem} -Djava.io.tmpdir={params.temp_folder}
-jar {params.jar_file} PE {params.options} {params.temp_folder}/temp_R1.fastq {params.temp_folder}/temp_R2.fastq -threads {threads} -baseout {params.temp_folder}/{wildcards.sample}.fastq.gz {params.processing_options} 2> {log}
        mv {params.temp_folder}/{wildcards.sample}*.fastq.gz 1000_processed_reads/{wildcards.sample}/reads/trimmomatic/
        """

rule mash:
    params : kmer = config['mash']['kmer'],
             hashes = config['mash']['hashes'],
    input : "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_1P.fastq.gz","1000_processed_reads/{sample}/reads/trimmomatic/{sample}_2P.fastq.gz"
    output : "1000_processed_reads/{sample}/reads/mash/{sample}.msh"
    log : "1000_processed_reads/{sample}/reads/mash/{sample}.log"
    threads : config['threads']
    shell :
        "mash sketch -r -p {threads} -k {params.kmer} -s {params.hashes} -o $(echo '{output}' | sed -e 's/.msh//') {input} > {log}"

rule kaiju:
    params : db_path = config['kaiju']['db_path'],
             db = config['kaiju']['db'],
             db = config['kaiju']['uppmax']
    input : "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_1P.fastq.gz","1000_processed_reads/{sample}/reads/trimmomatic/{sample}_2P.fastq.gz"
    output : "1000_processed_reads/{sample}/reads/kaiju/{sample}_kaiju.out.summary", "1000_processed_reads/{sample}/reads/kaiju/{sample}_kaiju.html"
    log : "1000_processed_reads/{sample}/reads/kaiju/{sample}_kaiju.log"
    threads : config['threads']
    shell : """
    module load bioinfo-tools
    module load Krona
    kaiju -t {params.db_path}/nodes.dmp -f {params.db_path}/{params.db}   -i 1000_processed_reads/{wildcards.sample}/reads/trimmomatic/{wildcards.sample}_1P.fastq.gz -j 1000_processed_reads/{wildcards.sample}/reads/trimmomatic/{wildcards.sample}_2P.fastq.gz -o 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.out -z {threads} > {log}
    kaiju2krona -u -t {params.db_path}/nodes.dmp -n {params.db_path}/names.dmp -i 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.out -o 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.out.krona >> {log}
    ktImportText  -o 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.html 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.out.krona >> {log}
    kaijuReport -p -r genus -t {params.db_path}/nodes.dmp -n {params.db_path}/names.dmp -i 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.out -r family -o 1000_processed_reads/{wildcards.sample}/reads/kaiju/{wildcards.sample}_kaiju.out.summary >> {log}
    """

rule matam:
    params : db_path = config['matam']['db_path'],
             temp_dir = config['temp_dir'],
             max_mem = config['matam']['max_mem']
    threads : config['threads']
    input :  fwd = "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_1P.fastq.gz",
             rev = "1000_processed_reads/{sample}/reads/trimmomatic/{sample}_2P.fastq.gz"
    output : dir =  "1000_processed_reads/{sample}/reads/matam/",
             fasta =  "1000_processed_reads/{sample}/reads/matam/final_assembly.fa",
    shell : """
    paste <(unpigz  -p {threads} -c {input.fwd} | paste  - - - -) <(unpigz {threads} -c {input.rev} | paste - - - -) | tr $"\t" $"\n" >  {params.temp_dir}/matam_{wildcards.sample}.fastq
    matam_assembly.py -d {params.db_path} -i {params.temp_dir}/matam_{wildcards.sample}.fastq --cpu {threads} --max_memory {params.max_mem} -v --perform_taxonomic_assignment -o {output.dir}
    """


rule all_kaiju:
    input : "1000_processed_reads/done"
    output : "1000_processed_reads/kaiju_table.tsv"
    run :
        from ete3 import NCBITaxa
        from collections import defaultdict
        import os
        from tqdm import tqdm
        from os.path import join as pjoin
        from pandas import DataFrame, concat

        out_file="1000_processed_reads/kaiju_table.tsv"

        pat = "/crex/proj/uppstore2018116/moritz6/1000_processed_reads/"
        samples = [s for s in os.listdir(pat) if "." not in s]
        out_dict = {}

        for s in tqdm(samples):
            if not out_dict.get(s):
                out_dict[s]=defaultdict(int)
                with open(pjoin(pat, s, "reads", "kaiju", s+"_kaiju.out")) as handle:
                    for l in tqdm(handle):
                        out_dict[s][l.split()[2]]+=1

        data = DataFrame.from_dict(out_dict)
        data = data.fillna(0)

        taxDb = NCBITaxa()
        line= {i : taxDb.get_lineage(i) for i in tqdm(list(data.index))}
        out = {i : taxDb.get_taxid_translator(l) if l else None for i,l in tqdm(line.items())}
        tt = sum([list(l.keys()) for l in tqdm(out.values()) if l], [])
        tt = list(set(tt))
        tt = taxDb.get_rank(tt)

        out_l = {k : {tt[k] : v for k,v in t.items()} if t else None for k,t in tqdm(out.items())}
        taxos = DataFrame.from_dict(out_l).transpose()
        taxos = taxos.fillna("NA")
        all = concat([data, taxos.loc[data.index]], axis=1)
	all.to_csv(out_file)







rule library:
    input :           "{path}/{sample}/reads/mash/{sample}.msh",
            "{path}/{sample}/megahit/mapping/mapping_rates.txt",
            "{path}/{sample}/reads/kaiju/{sample}_kaiju.out.summary"
    output : "{path}/{sample}/done"
    shell:
        "touch {wildcards.path}/{wildcards.sample}/done"



rule all_libraries :
    input : all_dones ,
    output : "1000_processed_reads/done"
    shell : "touch 1000_processed_reads/done"