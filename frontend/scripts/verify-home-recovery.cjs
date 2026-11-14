const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
(async()=>{
 const state=JSON.parse(fs.readFileSync(process.env.BETA_ACCEPTANCE_STATE||'/tmp/brasileirao-beta-state.json','utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});const ctx=await browser.newContext();
 await ctx.addCookies([{name:'bm_session',value:state.tokens[0],domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'}]);const page=await ctx.newPage();let errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/rooms',r=>r.request().method()==='GET'?r.fulfill({status:503,contentType:'application/json',body:'{"detail":"test unavailable"}'}):r.continue());
 await page.goto('http://localhost:5174/');await page.getByRole('button',{name:'Recarregar ligas'}).waitFor();await page.unroute('**/api/v1/rooms');await page.getByRole('button',{name:'Recarregar ligas'}).click();await page.getByRole('button',{name:'Recarregar ligas'}).waitFor({state:'hidden'});
 const name='Liga descoberta '+Date.now();const response=await ctx.request.post('http://localhost:8000/api/v1/rooms',{data:{name,mode:'FIVE_A_SIDE',initial_budget_cents:5000000000,max_human_participants:4,privacy:'PUBLIC'}});if(response.status()!==201)throw Error('Could not create public room');
 await page.locator('.public-rooms > .room-list .room-row').getByText(name,{exact:true}).first().waitFor({timeout:12000});if(errors.length)throw Error(JSON.stringify(errors));
 const output=process.env.BETA_ARTIFACTS||'/tmp/brasileirao-beta-artifacts';fs.writeFileSync(path.join(output,'home-recovery-verification.json'),JSON.stringify({retryRecovered:true,publicRoomsRefreshWithoutReload:true,errors},null,2));console.log('PASS home retry and new public rooms appear without reload');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
