export const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function values(f,nums=[]){let x=Object.fromEntries(new FormData(f));for(let k of nums)if(k in x)x[k]=+x[k];return x}
export const meters=x=>Number(x).toFixed(2)+' m';
export function options(rows,label){return rows.map(x=>`<option value="${x.id}">${esc(label(x))}</option>`).join('')}
