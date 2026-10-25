// Local artifact rendering only. No account, external page or production interaction.
const { chromium } = require('/Users/kimyongjin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path = require('path');
const { pathToFileURL } = require('url');
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:1100},deviceScaleFactor:1});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(pathToFileURL(path.join(__dirname,'outputs/profiles.html')).href);
  if(await page.locator('article:visible').count()!==216)throw Error('Initial runner count');
  await page.locator('#query').fill('비케이비바체');
  if(await page.locator('article:visible').count()!==1)throw Error('Horse search');
  await page.locator('article:visible details').first().locator('summary').click();
  await page.screenshot({path:path.join(__dirname,'outputs/profile_preview.png'),fullPage:false});
  await page.locator('#query').fill('부산');
  if(await page.locator('article:visible').count()===0)throw Error('Venue search');
  await page.setViewportSize({width:390,height:844});
  await page.locator('#query').fill('비케이비바체');
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
  if(overflow)throw Error('Mobile page overflow');
  if(errors.length)throw Error(errors.join('\n'));
  process.stdout.write(JSON.stringify({status:'passed',initialCards:216,horseSearch:true,venueSearch:true,mobileOverflow:false,pageErrors:errors})+'\n');
  await browser.close();
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exit(1)});
