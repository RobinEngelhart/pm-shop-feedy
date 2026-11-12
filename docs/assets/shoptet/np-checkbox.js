/* P+M shop – náhradní plnění v objednávce (krok 2). Načítá se ze Zápatí HTML kódů. */
(function(){var s=document.createElement('style');s.id='pmnp-css';s.textContent="@keyframes pmnpPulse{0%{box-shadow:0 0 0 0 rgba(37,99,235,.35)}70%{box-shadow:0 0 0 12px rgba(37,99,235,0)}100%{box-shadow:0 0 0 0 rgba(37,99,235,0)}}\n#pmnpBox{margin:18px 0;border:2px solid #BFD3EA;border-radius:16px;background:#fff;overflow:hidden;font-size:15px;line-height:1.45}\n#pmnpBox .pmnp-h{background:#EAF2FB;color:#1E3A5F;font-weight:800;font-size:15px;letter-spacing:.02em;padding:10px 16px;display:flex;gap:8px;align-items:center}\n#pmnpBox .pmnp-b{padding:16px}\n#pmnpBox label{display:flex;gap:14px;align-items:center;cursor:pointer;margin:0;background:#F6F9FD;border:2px dashed #93B4D8;border-radius:12px;padding:14px}\n#pmnpBox input#pmnpCk{position:static!important;clip:auto!important;appearance:auto!important;-webkit-appearance:checkbox!important;opacity:1!important;display:inline-block!important;width:30px!important;height:30px!important;flex:0 0 30px;margin:0!important;accent-color:#16A34A;cursor:pointer;border-radius:6px;animation:pmnpPulse 1.6s infinite}\n#pmnpBox .pmnp-l{font-size:19px;font-weight:800;color:#1F2125}\n#pmnpBox p{margin:12px 0 0;color:#3B3E44}\n#pmnpBox a{color:#1D4ED8;font-weight:700;text-decoration:underline}\n#pmnpBox .pmnp-ok{display:none;margin-top:12px;background:#ECFDF3;border:2px solid #16A34A;color:#166534;border-radius:10px;padding:10px 12px;font-weight:700}\n#pmnpBox.on{border-color:#16A34A}\n#pmnpBox.on .pmnp-h{background:#16A34A}\n#pmnpBox.on label{background:#ECFDF3;border-color:#16A34A;border-style:solid}\n#pmnpBox.on input#pmnpCk{animation:none}\n#pmnpBox.on .pmnp-ok{display:block}\n#pmnpErr{margin-top:12px;background:#FEF3C7;color:#78350F;border-radius:10px;padding:10px 12px;font-weight:700}\n#pmnpHint{display:block;margin:8px 0 4px;background:#F1F6FC;border-left:4px solid #93B4D8;border-radius:0 8px 8px 0;padding:8px 12px;font-size:14px;color:#1F2125}\n#pmnpHint a{color:#1D4ED8;font-weight:700}";document.head.appendChild(s)})();
(function(){
if(!/\/objednavka\/krok-2\//.test(location.pathname))return;
var MARK='*** NÁHRADNÍ PLNĚNÍ – ANO ***';
function init(){
var f=document.getElementById('order-form');if(!f||document.getElementById('pmnpBox'))return;
var rm=f.querySelector('[name=remark]'),cs=f.querySelector('[name=companyShopping]'),ic=f.querySelector('[name=companyId]'),btn=document.getElementById('submit-order');
var box=document.createElement('div');box.id='pmnpBox';
box.innerHTML='<div class="pmnp-h">Nakupujete v rámci náhradního plnění?</div><div class="pmnp-b"><label><input type="checkbox" id="pmnpCk"><span class="pmnp-l">Ano, nakupuji v rámci náhradního plnění</span></label><p>Aby se objednávka započítala do <strong>náhradního plnění povinného podílu OZP</strong>, <strong>musíte toto políčko zaškrtnout</strong> a vyplnit údaje firmy včetně IČO. <strong>Bez zaškrtnutí ji do evidence MPSV zapsat nemůžeme.</strong> <a href="/nahradni-plneni/" target="_blank">Co je náhradní plnění</a></p><div class="pmnp-ok">✓ Objednávku vyfakturujeme jako náhradní plnění a po zaplacení ji zapíšeme do evidence MPSV.</div><div id="pmnpErr" hidden>Pro náhradní plnění zaškrtněte „Nakupuji na firmu“ a vyplňte IČO.</div></div>';
var zip=f.querySelector('[name=billZip]'),zg=zip?(zip.closest('.form-group')||zip.parentNode):null,ci=document.getElementById('company-info');
if(zg&&zg.parentNode)zg.parentNode.insertBefore(box,zg.nextSibling);else if(ci)ci.appendChild(box);else{var anchor=btn?btn.closest('.next-step, .order-summary-item, .form-group, div'):null;if(anchor&&anchor.parentNode)anchor.parentNode.insertBefore(box,anchor);else f.appendChild(box);}
if(cs){var w=cs.closest('.form-group')||cs.parentNode;var h=document.createElement('div');h.id='pmnpHint';h.innerHTML='Nakupujete v rámci <strong>náhradního plnění</strong>? Zaškrtněte „Nakupuji na firmu“ a zobrazí se vám políčko pro náhradní plnění.';w.parentNode.insertBefore(h,w.nextSibling)}
var ck=box.querySelector('input'),err=box.querySelector('#pmnpErr');
function upd(){var on=ck.checked;box.classList.toggle('on',on);try{sessionStorage.setItem('pmnp',on?'1':'')}catch(e){}
if(rm){var v=rm.value.split(MARK).join('').replace(/^\s+/,'');rm.value=on?(MARK+(v?'\n'+v:'')):v}
if(on&&cs&&!cs.checked)cs.click();if(!on)err.hidden=true}
ck.addEventListener('change',upd);
function vis(){var on=!cs||cs.checked;box.style.display=on?'':'none';var h=document.getElementById('pmnpHint');if(h)h.style.display=on?'none':'';if(!on&&ck.checked){ck.checked=false;upd()}}
if(cs){cs.addEventListener('change',vis);cs.addEventListener('click',function(){setTimeout(vis,0)})}
try{if(sessionStorage.getItem('pmnp')==='1'||(rm&&rm.value.indexOf(MARK)>-1)){ck.checked=true;upd()}}catch(e){}
vis();
f.addEventListener('submit',function(e){if(ck.checked&&(!cs||!cs.checked||!ic||!ic.value.trim())){e.preventDefault();e.stopImmediatePropagation();err.hidden=false;if(cs&&!cs.checked)cs.click();if(ic)setTimeout(function(){ic.focus()},50)}},true);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
