const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const fs=require('fs'),path=require('path');
const assert=(v,m)=>{if(!v)throw Error(m)};
const sizes=[[375,812],[390,844],[768,1024],[1280,720],[1366,768],[1600,900],[1920,1080]];
const output=process.env.BETA_ARTIFACTS||'/tmp/brasileirao-beta-artifacts';fs.mkdirSync(output,{recursive:true});
(async()=>{
 const state=JSON.parse(fs.readFileSync(process.env.BETA_ACCEPTANCE_STATE||'/tmp/brasileirao-beta-state.json','utf8'));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const report={viewports:sizes,screens:[],actions:[],accessibility:[],errors:[]};
 const save=()=>fs.writeFileSync(path.join(output,'beta-verification.json'),JSON.stringify(report,null,2));
 const ctx=await browser.newContext({viewport:{width:1366,height:768},reducedMotion:'reduce'});
 const cookie={name:'bm_session',value:state.tokens[0],domain:'localhost',path:'/',httpOnly:true,sameSite:'Lax'};
 await ctx.addCookies([cookie]);const page=await ctx.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 const go=async name=>{
  await page.goto('http://localhost:5174/');
  await Promise.all([page.waitForNavigation({waitUntil:'domcontentloaded'}),page.evaluate(id=>{if(id)localStorage.setItem('bm_active_room',id);else localStorage.removeItem('bm_active_room');window.location.reload()},state.rooms[name]||null)]);await page.locator('.room-toolbar, .home-reference').first().waitFor();await page.waitForTimeout(450);
 };
 for(const name of ['home','lobby','market','selection','reassignment','review','squad5','squad11','season','postmatch','transfers','champion','history']){
  await go(name);
  for(const [width,height]of sizes){
   await page.setViewportSize({width,height});await page.waitForTimeout(100);
   const over=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,nodes:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+2).slice(0,6).map(e=>e.className)}));
   assert(over.scroll<=width+1,`${name} overflow ${width} ${JSON.stringify(over)}`);
   if(width===390||width===1366){
    await page.screenshot({path:path.join(output,`${name}-${width}.png`),fullPage:true});
    const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    report.accessibility.push({screen:name,width,violations:result.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))});save();
   }
  }
  report.screens.push({name,viewports:7});save();console.log('SCREEN PASS',name);
 }
 await go('home');await page.getByRole('button',{name:'Criar minha liga'}).click();await page.getByRole('dialog').waitFor();await page.keyboard.press('Shift+Tab');
 assert(await page.getByRole('dialog').evaluate(el=>el.contains(document.activeElement)),'Modal focus escaped');await page.keyboard.press('Escape');assert(!await page.getByRole('dialog').count(),'Escape failed');report.actions.push('Settings keyboard trap and Escape');
 await page.getByRole('button',{name:'Criar minha liga'}).click();await page.getByLabel('Nome da liga').fill('Liga UI beta');await page.getByRole('button',{name:'Escolher meu clube',exact:true}).click();await page.getByRole('button',{name:'Palmeiras: Livre'}).click();await page.getByRole('button',{name:'Fechar com esse time'}).click();await page.getByRole('dialog').waitFor({state:'hidden'});report.actions.push('Create real room and select club through accessible confirmation');

 await go('market');assert(await page.locator('.market-player').count()===24,'Catalog pagination failed');await page.getByRole('button',{name:'Próxima página'}).click();assert(await page.locator('.market-player').count()<=24,'Pagination renders too many cards');report.actions.push('Catalog renders 24 players/page');await page.getByRole('button',{name:'Alterar valor'}).first().click();await page.getByLabel('Sua proposta em reais (R$)').fill('120000');await page.getByRole('button',{name:'Salvar novo valor'}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
 const market=(await(await ctx.request.get(`http://localhost:8000/api/v1/rooms/${state.rooms.market}/market`)).json()).data;assert(market.offers.some(o=>o.amount_cents===12000000),'Offer cents mismatch');report.actions.push('Real edit secret offer reais -> server cents');
 await go('squad5');await page.getByRole('button',{name:'Salvar escalação',exact:true}).click();await page.waitForTimeout(400);
 const squad=(await(await ctx.request.get(`http://localhost:8000/api/v1/rooms/${state.rooms.squad5}/squad`)).json()).data;assert(squad.lineup?.evaluation.length===5,'Save lineup failed');report.actions.push('Save real 5x5 lineup');
 await go('transfers');await page.getByRole('button',{name:'Colocar à venda',exact:true}).first().click();await page.getByRole('button',{name:'Retirar anúncio',exact:true}).first().waitFor();report.actions.push('Real transfer listing');
 await go('history');await page.getByRole('button',{name:'Abrir histórico do clube'}).click();await page.getByRole('button',{name:'Evolução do elenco'}).click();await page.locator('.career-ledger tbody tr').first().waitFor();report.actions.push('Real career progression and ledger');
 const blocked=await browser.newContext();await blocked.addCookies([cookie]);await blocked.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}}));
 const bp=await blocked.newPage();bp.on('pageerror',e=>report.errors.push(e.message));await bp.goto('http://localhost:5174/');await bp.getByText('Voltar para minhas ligas',{exact:true}).waitFor();report.actions.push('Blocked localStorage recovers server memberships');
 const network=await browser.newContext();const np=await network.newPage();let guests=0;np.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/auth/guest'))guests++});await np.route('**/api/v1/me',r=>r.fulfill({status:503,contentType:'application/json',body:'{"detail":"test failure"}'}));await np.goto('http://localhost:5174/');await np.getByRole('button',{name:'Tentar novamente'}).waitFor();assert(guests===0,'Identity replaced on503');report.actions.push('503 auth does not create a new guest');
 report.seriousAccessibility=report.accessibility.flatMap(r=>r.violations.filter(v=>['critical','serious'].includes(v.impact)).map(v=>({screen:r.screen,width:r.width,...v})));save();
 assert(!report.errors.length,'Page errors '+JSON.stringify(report.errors));assert(!report.seriousAccessibility.length,'Axe serious '+JSON.stringify(report.seriousAccessibility.slice(0,3)));console.log('PASS all screens, viewports, real actions, recovery and axe');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
