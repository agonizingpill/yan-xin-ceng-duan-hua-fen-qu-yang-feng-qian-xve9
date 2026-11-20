import hashlib,json
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import train_test_split
from sklearn.metrics import adjusted_rand_score
SEED=42
FEATURES=['density','susceptibility','velocity']
def fit_layers(rows):
    if len(rows)<12:raise ValueError('至少12个真实测点')
    raw=np.array([[r[k]for k in FEATURES]for r in rows],dtype=float)
    if not np.isfinite(raw).all()or np.any(raw.std(axis=0)<1e-6):raise ValueError('物性缺少变化或包含非有限值')
    train_idx,held_idx=train_test_split(np.arange(len(rows)),test_size=.2,random_state=SEED)
    scaler=StandardScaler().fit(raw[train_idx]);train=scaler.transform(raw[train_idx]);held=scaler.transform(raw[held_idx]);whole=scaler.transform(raw)
    models=[GaussianMixture(n_components=k,random_state=SEED,n_init=5,reg_covar=.01).fit(train)for k in range(1,min(5,len(train)//3)+1)]
    best=min(models,key=lambda m:m.bic(train));prob=best.predict_proba(whole);labels=best.predict(whole);ordered=np.argsort(scaler.inverse_transform(best.means_)[:,0]);rename={int(old):int(new)+1 for new,old in enumerate(ordered)}
    # Holdout readings never enter scaler fitting/BIC choice. Stability compares two train-only fits on the same holdout.
    rng=np.random.default_rng(SEED);boot_idx=rng.choice(len(train),len(train),replace=True);boot=GaussianMixture(n_components=best.n_components,random_state=43,n_init=5,reg_covar=.01).fit(train[boot_idx]);ari=adjusted_rand_score(best.predict(held),boot.predict(held))
    classified=[{'reading_id':r['id'],'depth_m':r['depth_m'],'cluster':rename[int(l)],'posterior':round(float(max(p)),6),'density':r['density'],'susceptibility':r['susceptibility'],'velocity':r['velocity']}for r,l,p in zip(rows,labels,prob)]
    contacts=[round((a['depth_m']+b['depth_m'])/2,4)for a,b in zip(classified,classified[1:])if a['cluster']!=b['cluster']]
    checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'algorithm':'StandardScaler + GaussianMixture, train-only BIC','random_state':SEED,'features':FEATURES,'source_sha256':checksum,'source_count':len(rows),'train_count':len(train_idx),'holdout_count':len(held_idx),'train_reading_ids':[rows[i]['id']for i in train_idx],'holdout_reading_ids':[rows[i]['id']for i in held_idx],'bic_candidates':[{'k':m.n_components,'bic':round(float(m.bic(train)),6)}for m in models],'chosen_k':best.n_components,'holdout_mean_log_likelihood':round(float(best.score(held)),6),'holdout_stability_ari':round(float(ari),6),'cluster_centers':[{'cluster':rename[int(k)],**{f:round(float(v),5)for f,v in zip(FEATURES,c)}}for k,c in enumerate(scaler.inverse_transform(best.means_))],'classified':classified,'suggested_contacts_m':contacts,'note':'成分相似性不是岩性真值；接触面须编录员人工解释并主管确认'}
