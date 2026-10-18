/* Visual QA: requires Playwright in NODE_PATH or the Codex runtime. */
const fs = require('node:fs');
const path = require('node:path');
let playwright;
try { playwright = require('playwright'); }
catch (_) { playwright = require(path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }
const phase = process.argv[2] || 'after';
const root = path.resolve(__dirname, '../outputs/ui-qa');
const info = JSON.parse(fs.readFileSync(path.join(root, `${phase}-session.json`), 'utf8'));
const dir = path.join(root, phase);
fs.mkdirSync(dir, {recursive:true});
const checks = [], errors = [];
const assert = (ok, message) => { if (!ok) throw new Error(message); };
(async () => {
  const browser = await playwright.chromium.launch({channel:'msedge',headless:true});
  try {
    if (process.argv.includes('--inspect')) {
      const ctx = await browser.newContext({viewport:{width:390,height:844}});
      await ctx.addCookies([{name:'sessionid',value:info.admin_session,url:info.base}]);
      const p = await ctx.newPage();
      await p.goto(info.base+(process.argv[4] || '/admin/auth/user/'));
      console.log(JSON.stringify(await p.evaluate(() => [...document.querySelectorAll('#content,#changelist,.changelist-form-container,.actions,.actions label,.actions select,.submit-row,.submit-row input,.form-row,.form-row .flex-container,fieldset')].slice(0,25).map(el => {const s=getComputedStyle(el);const r=el.getBoundingClientRect();return {el:el.tagName+'.'+el.className,width:r.width,x:r.x,height:r.height,css:{width:s.width,minWidth:s.minWidth,flex:s.flex,flexDirection:s.flexDirection,padding:s.padding,margin:s.margin,boxSizing:s.boxSizing}};})),null,2));
      return;
    }
    const context = await browser.newContext();
    await context.addCookies([{name:'sessionid', value:info.admin_session, url:info.base}]);
    const page = await context.newPage();
    page.on('pageerror', err => errors.push(err.message));
    page.on('response', res => {if (res.status() >= 400 && res.url().includes('/static/')) errors.push(`Asset ${res.status()} ${res.url()}`);});
    const query = `?semester=${info.semester}&faculty=${info.faculty}`;
    const pages = [
      ['dashboard','/admin/'], ['auto','/admin/auto-schedule/'],
      ['run',`/admin/auto-schedule/?run=${info.run}`],
      ['review','/admin/review-schedules/'+query], ['review-empty','/admin/review-schedules/'],
      ['timetable','/admin/faculty-timetable/'+query], ['timetable-empty','/admin/faculty-timetable/'],
      ['export','/admin/export-assignments/'+query], ['export-empty','/admin/export-assignments/'],
      ['import-courses','/admin/import-catalog/courses/'], ['import-rooms','/admin/import-catalog/rooms/'],
      ['import-lecturers','/admin/import-catalog/lecturers/'], ['import-schedule','/admin/import-schedule/'],
      ['edit',`/admin/review-schedules/${info.entry}/edit/`], ['password','/admin/password_change/'],
      ['school','/admin/school/'], ['auth','/admin/auth/'],
      ['users','/admin/auth/user/'], ['user-add','/admin/auth/user/add/'],
      ['groups','/admin/auth/group/'], ['group-add','/admin/auth/group/add/'],
    ];
    for (const [model,id] of Object.entries(info.models)) {
      pages.push([`${model}-list`,`/admin/school/${model}/`],
        [`${model}-add`,`/admin/school/${model}/add/`],
        [`${model}-change`,`/admin/school/${model}/${id}/change/`]);
    }
    const sizes = phase === 'after'
      ? [['desktop',1440,1000], ['laptop',1280,800], ['tablet',768,1024], ['mobile',390,844]]
      : [['desktop',1440,1000], ['mobile',390,844]];
    for (const [size,width,height] of sizes) {
      await page.setViewportSize({width,height});
      for (const [name,url] of pages) {
        const response = await page.goto(info.base+url);
        assert(response.status() === 200, `${url}: ${response.status()}`);
        assert(!page.url().includes('/login/'), `Unexpected authentication redirect: ${url}`);
        await page.evaluate(() => document.fonts.ready);
        const layout = await page.evaluate(() => {
          const root = document.documentElement;
          const overflow = [...document.querySelectorAll('main *')].filter(el => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.right > innerWidth+2 && !el.closest('.table-wrap,.results,.selector select,.calendarbox,.clockbox') && getComputedStyle(el).position !== 'absolute';
          }).slice(0,8).map(el => `${el.tagName}.${el.className}`);
          const contrast = [...document.querySelectorAll('h1,h2,.fieldset-heading')].filter(el => el.getBoundingClientRect().height).map(el => ({text:el.textContent.trim().slice(0,45), color:getComputedStyle(el).color, bg:getComputedStyle(el).backgroundColor}));
          return {width:root.clientWidth,scroll:root.scrollWidth,overflow,contrast};
        });
        checks.push({size,name,url,...layout});
        if (['dashboard','auto','review','timetable','export','import-courses','edit','group-add','lecturer-add','building-add','room-add','users'].includes(name)) {
          await page.screenshot({path:path.join(dir,`${size}-${name}.png`),fullPage:true});
        }
      }
      const anon = await browser.newContext({viewport:{width,height}});
      const login = await anon.newPage();
      for (const url of ['/login/','/admin/login/']) {
        await login.goto(info.base+url);
        await login.screenshot({path:path.join(dir,`${size}-${url.includes('admin')?'admin-login':'login'}.png`),fullPage:true});
      }
      await anon.close();
    }
    if (phase === 'after') {
      await page.setViewportSize({width:1440,height:1000});
      await page.goto(info.base+'/admin/');
      await page.locator('#uiMenuToggle').click();
      assert(await page.locator('body').evaluate(el => el.classList.contains('nav-collapsed')), 'Desktop sidebar did not collapse');
      await page.locator('#uiMenuToggle').click();
      await page.locator('#uiThemeToggle').click();
      assert(await page.locator('html').getAttribute('data-theme') === 'dark','Theme did not switch');
      await page.reload();
      assert(await page.locator('html').getAttribute('data-theme') === 'dark','Theme did not persist');
      await page.screenshot({path:path.join(dir,'desktop-dark-dashboard.png'),fullPage:true});
      await page.goto(info.base+'/admin/auth/group/add/');
      await page.screenshot({path:path.join(dir,'desktop-dark-group.png'),fullPage:true});
      await page.locator('#uiThemeToggle').click();
      await page.setViewportSize({width:390,height:844});
      await page.locator('#uiMenuToggle').click();
      assert(await page.locator('#uiMenuToggle').getAttribute('aria-expanded') === 'true', 'Mobile menu did not open');
      await page.screenshot({path:path.join(dir,'mobile-navigation.png'),fullPage:true});
      await page.keyboard.press('Escape');
      assert(await page.locator('#uiMenuToggle').getAttribute('aria-expanded') === 'false','Escape did not close mobile navigation');
      assert(await page.evaluate(() => document.activeElement.id) === 'uiMenuToggle','Focus was not returned');
      // Exercise Django's real permission widget and save on the isolated QA DB.
      await page.setViewportSize({width:1440,height:1000});
      await page.goto(info.base+'/admin/auth/group/add/');
      await page.locator('#id_name').fill(`Nhóm kiểm thử trình duyệt ${Date.now()}`);
      await page.locator('#id_permissions_input').pressSequentially('Giảng viên');
      assert((await page.locator('#id_permissions_from option').first().textContent()).includes('Giảng viên'),'Permission search did not filter the list');
      const option = page.locator('#id_permissions_from option').first();
      const selectedPermission = await option.getAttribute('value');
      await page.locator('#id_permissions_from').selectOption(selectedPermission);
      await page.locator('#id_permissions_add').click();
      assert(await page.locator('#id_permissions_to option').count() === 1,'Selected permission missing');
      await page.locator('input[name=_continue]').click();
      await page.waitForURL(/\/change\//);
      assert(await page.locator('#id_permissions_to option').count() === 1,'Saved permission selection changed');
      await page.screenshot({path:path.join(dir,'desktop-permission-saved.png'),fullPage:true});
      // Review selection enables the action only after a real checkbox selection.
      await page.goto(info.base+'/admin/review-schedules/'+query);
      const approve = page.locator('form.approve button[type=submit]');
      assert(await approve.isDisabled(),'Approval must start disabled with zero selections');
      await page.locator('#selectAllEntries').check();
      assert(await approve.isEnabled(),'Approval did not enable for selected pending entry');
      await page.locator('#selectAllEntries').uncheck();
      assert(await approve.isDisabled(),'Approval did not reset');
      // File selection feedback must show the actual local filename.
      await page.goto(info.base+'/admin/auto-schedule/');
      await page.locator('#courses').setInputFiles(path.join(root,'courses.xlsx'));
      assert((await page.locator('.file-feedback').first().textContent()).includes('courses.xlsx'),'Missing file feedback');
      // Download uses the real export endpoint and preserves its action parameter.
      await page.goto(info.base+'/admin/export-assignments/'+query);
      const downloadWait = page.waitForEvent('download');
      await page.locator('button[name=action][value=download]').click();
      const download = await downloadWait;
      assert(download.suggestedFilename().endsWith('.xlsx'),'Excel download failed');
      await download.saveAs(path.join(dir,'export.xlsx'));
      // Invalid workbooks should return visible errors without leaving the form busy.
      const invalidFile = path.join(root,'invalid.xlsx');
      fs.writeFileSync(invalidFile,'This is an intentionally invalid QA workbook.');
      await page.goto(info.base+'/admin/import-catalog/rooms/');
      await page.locator('#file').setInputFiles(invalidFile);
      await page.locator('main button[type=submit]').click();
      await page.locator('main .error').first().waitFor();
      assert(await page.locator('main form').first().getAttribute('aria-busy') !== 'true','Error response left upload form busy');
      await page.screenshot({path:path.join(dir,'desktop-import-error.png'),fullPage:true});
      // Built-in validation stays visible after submitting an incomplete Admin form.
      await page.goto(info.base+'/admin/school/building/add/');
      await page.locator('input[name=_save]').click();
      await page.locator('.errornote').waitFor();
      await page.screenshot({path:path.join(dir,'desktop-form-error.png'),fullPage:true});
    }
    const teacherContext = await browser.newContext({viewport:{width:390,height:844}});
    await teacherContext.addCookies([{name:'sessionid',value:info.teacher_session,url:info.base}]);
    const teacherPage = await teacherContext.newPage();
    await teacherPage.goto(info.base+'/portal/');
    await teacherPage.screenshot({path:path.join(dir,'mobile-portal.png'),fullPage:true});
    await teacherContext.close();
    fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify({checks,errors},null,2));
    const overflows = checks.filter(row => row.scroll > row.width+2);
    console.log(JSON.stringify({phase,pages:checks.length,errors,overflows:overflows.map(({size,name,width,scroll,overflow})=>({size,name,width,scroll,overflow}))},null,2));
    assert(errors.length === 0,'JavaScript or static asset errors');
    if (phase === 'after') assert(overflows.length === 0,'Pages overflow the viewport');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
