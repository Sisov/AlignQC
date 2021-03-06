#!/usr/bin/python
import sys, argparse, gzip, re
from Bio.Format.GPD import GPD
from multiprocessing import cpu_count, Pool, Lock

glock = Lock()
of = sys.stdout
sys.setrecursionlimit(10000)
chrdone  = 0
chrtotal = 0

# Outputs annotations
#1. read line number              
#2. read name
#3. gene_name
#4. transcript name
#5. match type
#6. number of matching exons
#7. highst number of consecutive_exons
#8. number of exons in read
#9. number of exons in reference transcript
#10. number of bp overlapping
#11. read lengthread_length
#12. transcript length
#13. read range
#14. transcript range
#15. reference line number

def main(args):

  global of
  if args.output:
    if re.search('\.gz$',args.output):
      of = gzip.open(args.output,'w')
    else:
      of = open(args.output,'w')

  #read the reference gpd
  rinf = None
  txome = {}
  if re.search('\.gz$',args.reference):
    rinf = gzip.open(args.reference)
  else:
    rinf = open(args.reference)
  sys.stderr.write("Reading in reference\n")
  z = 0
  for line in rinf:
    z += 1
    gpd = GPD(line)
    gpd.set_payload(z)
    if z%100 == 0:  sys.stderr.write(str(z)+"          \r")
    if gpd.value('chrom') not in txome: txome[gpd.value('chrom')] = []
    r = gpd.get_range()
    r.set_payload(gpd)
    txome[gpd.value('chrom')].append(r)
  rinf.close()
  sys.stderr.write(str(z)+"          \r")
  sys.stderr.write("\n")
  inf = sys.stdin
  if args.input != '-':
    if re.search('\.gz$',args.input):
      inf = gzip.open(args.input)
    else:
      inf = open(args.input)
  z = 0
  chroms = {}
  sys.stderr.write("Buffering reads\n")
  for line in inf:
    z += 1
    m = re.match('[^\t]*\t[^\t]*\t([^\t]+)',line)
    chrom = m.group(1)
    if z%100==0:  sys.stderr.write(str(z)+"      \r")
    if chrom not in chroms:
      chroms[chrom] = []
    chroms[chrom].append([line,z])
  sys.stderr.write("\n")
  sys.stderr.write("Finished buffering reads\n")
  if args.threads > 1:
    p = Pool(processes=args.threads)
  results = []
  global chrtotal
  chrtotal = len(chroms)
  for chrom in chroms:
    if chrom not in txome: continue
    if args.threads > 1:
      v = p.apply_async(do_buffer,args=(chroms[chrom],{chrom:txome[chrom]},args),callback=do_out)
      results.append(v)
    else:
      v = do_buffer(chroms[chrom],{chrom:txome[chrom]},args)
      results.append(Queue(v))
      do_out(v)
  if args.threads > 1:
    p.close()
    p.join()
  sys.stderr.write("\n")
  for res in [x.get() for x in results]:
    for oline in res:
      of.write(oline)
  inf.close()
  of.close()

class Queue:
  def __init__(self,val):
    self.val = val
  def get(self):
    return self.val

def do_out(results):
  global glock
  global chrtotal
  global chrdone
  glock.acquire()
  chrdone+=1
  sys.stderr.write(str(chrdone)+'/'+str(chrtotal)+" groups finished    \r")
  glock.release()

def do_buffer(buffer,txome,args):
  results = []
  for line_z in buffer:
    z = line_z[1]
    line = line_z[0]
    gpd = GPD(line)
    v = annotate_line(gpd,txome,args)
    if not v: continue
    type = 'partial'
    if v[0]: type = 'full'
    exon_count = v[2]    
    most_consecutive_exons = v[3]
    read_exon_count = v[4]
    tx_exon_count = v[5]
    overlap_size = v[6]
    read_length = v[7]
    tx_length = v[8]
    results.append(str(z)+"\t"+gpd.get_gene_name()+"\t"+v[9].get_gene_name()+"\t"+v[9].get_transcript_name()+"\t"+type+"\t"+\
          str(exon_count)+"\t"+str(most_consecutive_exons)+"\t"+str(read_exon_count)+"\t"+str(tx_exon_count)+"\t"+\
          str(overlap_size)+"\t"+str(read_length)+"\t"+str(tx_length)+"\t"+gpd.get_range().get_range_string()+"\t"+v[9].get_range().get_range_string()+"\t"+str(v[9].get_payload())+"\n")
  return results

def annotate_line(gpd,txome,args):
  v = gpd.get_range()
  if v.chr not in txome: return None
  possible = [x.get_payload() for x in txome[v.chr] if x.overlaps(v)]
  candidates = []
  if len(possible) == 0: return None
  for tx in possible:
    eo = None
    full = False
    subset = False
    econsec = 1
    if tx.get_exon_count() == 1 or gpd.get_exon_count() == 1:
      eo = gpd.exon_overlap(tx,single_minover=100,single_frac=0.5)
    else:
      eo = gpd.exon_overlap(tx,multi_minover=10,multi_endfrac=0,multi_midfrac=0.8,multi_consec=False)
      if eo.is_full_overlap():
        full = True
      if eo.is_subset():
        subset = True
      if eo:
        econsec = eo.consecutive_exon_count()
    if not eo: continue
    ecnt = eo.match_exon_count()
    osize = gpd.overlap_size(tx)
    candidates.append([full,subset,ecnt,econsec,gpd.get_exon_count(),tx.get_exon_count(),osize,gpd.get_length(),tx.get_length(),tx])
  if len(candidates)==0: return None
  bests = sorted(candidates,key=lambda x: (-x[0],-x[1],-x[3],-x[2],-min(float(x[6])/float(x[7]),float(x[6])/float(x[8]))))
  return bests[0]

def do_inputs():
  parser = argparse.ArgumentParser(description="",formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('input',help="Use - for STDIN")
  parser.add_argument('-o','--output',help="output file otherwise STDOUT")
  parser.add_argument('--threads',type=int,default=cpu_count(),help="Number of threads to convert names")
  parser.add_argument('-r','--reference',required=True,help="reference gpd")
  args = parser.parse_args()
  return args
  
def external_cmd(cmd):
  cache_argv = sys.argv
  sys.argv = cmd.split()
  args = do_inputs()
  main(args)
  sys.argv = cache_argv

if __name__=="__main__":
  args = do_inputs()
  main(args)
