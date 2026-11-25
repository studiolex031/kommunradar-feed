const {chromium}=require('playwright');
(async()=>{
 global.T0=Date.now();const b=await chromium.launch();const p=await b.newPage();
 const log=[];p.on('console',m=>log.push('console '+m.type()+': '+m.text()));p.on('pageerror',e=>log.push('pageerror: '+e.message));
 p.on('response',async r=>{if(r.url().includes('checkout.php')){log.push('T+'+(Date.now()-T0));let t='';try{t=(await r.text()).slice(0,300)}catch(e){}log.push('API '+r.status()+' '+t)}});
 p.on('request',r=>{if(r.url().includes('checkout.php'))log.push('T+'+(Date.now()-T0)+' POST '+r.postData());if(/stripe|checkout/.test(r.url()))log.push('REQ '+r.method()+' '+r.url().slice(0,120))});
 await p.route(/checkout\.stripe\.com|buy\.stripe\.com/,r=>{log.push('T+'+(Date.now()-T0)+' NAV-STRIPE '+r.request().url().slice(0,100));r.fulfill({body:'stripe'})});
 await p.goto('https://kommunradar.online/?n='+Date.now(),{waitUntil:'networkidle'});
 const html=await p.content();require('fs').writeFileSync('live.html',html);
 const links=await p.$$eval('a[href*="stripe"],[data-buy],[data-checkout],#pris a,#pris button',els=>els.map(e=>e.outerHTML.slice(0,220)));
 console.log('LINKS\n'+links.join('\n'));
 const sel=['a.bwcta','a[href*="bJe4gy"]','#pris a[data-buy]','[data-checkout]'];
 for(const s of sel){const el=await p.$(s);if(!el){console.log('MISSING',s);continue}
   log.length=0;const t0=Date.now();global.T0=t0;
   await p.fill('#q','städ');await p.selectOption('#lan',{index:3}).catch(e=>log.push('sel '+e.message));await p.click('#go').catch(()=>{});await p.waitForTimeout(800);log.push('lanval='+await p.$eval('#lan',e=>e.value));await el.scrollIntoViewIfNeeded();await el.click({noWaitAfter:true}).catch(e=>log.push('clickerr '+e.message));
   await p.waitForTimeout(9000);console.log('== CLICK',s,'url now',p.url(),'after',Date.now()-t0,'ms\n'+log.join('\n'));
   await p.goto('https://kommunradar.online/?n='+Date.now(),{waitUntil:'networkidle'});}
 await b.close();})();
