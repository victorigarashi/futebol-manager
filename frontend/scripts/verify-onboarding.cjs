const { chromium }=require('playwright');
const AxeBuilder=require('@axe-core/playwright').default;
const fs=require('fs'),path=require('path');
const output=process.env.BETA_ARTIFACTS||'/tmp/brasileirao-beta-artifacts';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox']});
 const ctx=await browser.newContext(),page=await ctx.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.goto('http://localhost:5174/');await page.getByLabel('Antes da bola rolar, como a galera vai te chamar?').waitFor();
 const axe=[];
 for(const [width,height]of [[375,812],[390,844],[768,1024],[1280,720],[1366,768],[1600,900],[1920,1080]]){
  await page.setViewportSize({width,height});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Onboarding overflow '+width);
  if(width===390||width===1366){await page.screenshot({path:path.join(output,`onboarding-${width}.png`),fullPage:true});axe.push(...(await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations);}
 }
 await page.getByLabel('Antes da bola rolar, como a galera vai te chamar?').fill('Lia Beta');await page.getByRole('button',{name:'Bora jogar!'}).click();await page.getByRole('button',{name:'Criar minha liga'}).waitFor();
 const first=(await(await ctx.request.get('http://localhost:8000/api/v1/me')).json()).data;
 await page.reload();await page.getByRole('button',{name:'Editar perfil do técnico'}).click();await page.getByRole('dialog').waitFor();await page.getByLabel('Nome do técnico').fill('Lia Campea');await page.getByRole('button',{name:'Salvar nome',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
 const second=(await(await ctx.request.get('http://localhost:8000/api/v1/me')).json()).data;
 if(first.id!==second.id||second.display_name!=='Lia Campea')throw Error('Profile identity changed');
 await page.getByRole('button',{name:'Criar minha liga'}).click();await page.getByRole('dialog').waitFor();
 await page.screenshot({path:path.join(output,'settings-modal-1366.png')});axe.push(...(await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations);
 await page.keyboard.press('Escape');
 fs.writeFileSync(path.join(output,'onboarding-verification.json'),JSON.stringify({viewports:7,profileIdentityPreserved:true,errors,axeViolations:axe.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)}))},null,2));
 if(errors.length||axe.length)throw Error(JSON.stringify({errors,axe:axe.map(v=>v.id)}));console.log('PASS onboarding 7 viewports, edit/reload same identity, settings modal, axe');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
