const {chromium}=require('playwright');
(async()=>{
 const b=await chromium.launch();const p=await b.newPage();const log=[];
 p.on('request',r=>{if(r.url().includes('checkout.php'))log.push('POST '+r.postData())});
 p.on('response',r=>{if(r.url().includes('checkout.php'))log.push('API '+r.status())});
 await p.goto('https://kommunradar.online/?n='+Date.now(),{waitUntil:'networkidle'});
 const js=await (await p.request.get('https://kommunradar.online/checkout-prefill.js?n='+Date.now())).text();
 console.log('new js live:',js.includes('Öppnar kassan'));
 await p.fill('#q','städ');await p.selectOption('#lan',{index:3});
 const f='a[href*="7sYeVc"]:not(.bwcta)';
 for (const step of ['1st','2nd-after-back']){
   await p.click(f,{noWaitAfter:true});
   try{await p.waitForURL(/checkout\.stripe\.com/,{timeout:10000});console.log(step,'OK ->',p.url().slice(0,60))}catch(e){console.log(step,'FAILED url',p.url())}
   await p.goBack({waitUntil:'load'});await p.waitForTimeout(800);
 }
 await p.goto('https://kommunradar.online/?n='+Date.now(),{waitUntil:'networkidle'});
 console.log('after reload q=',JSON.stringify(await p.inputValue('#q')));
 await p.click('a[href*="bJe4gy"]',{noWaitAfter:true});
 try{await p.waitForURL(/checkout\.stripe\.com/,{timeout:10000});console.log('reload-yearly OK')}catch(e){console.log('reload-yearly FAILED',p.url())}
 console.log(log.join('\n'));await b.close();})();
