/*
 * 瀏覽器端行為的測試。
 *
 * 為什麼需要這個檔：按鈕該不該變灰、重新整理後欄位有沒有清空，
 * 這些是瀏覽器做的事，用 curl 或 Python 測不到 ——
 * 「重新整理沒清空」這個 bug 就是修了兩次都沒修好，直到用真瀏覽器跑才抓到。
 *
 * 執行方式（需要兩個終端機視窗）：
 *   視窗 1：  python app.py
 *   視窗 2：  node test_browser.js
 *
 * 如果出現「Cannot find module 'playwright'」，先裝一次：
 *   npm install playwright && npx playwright install chromium
 *
 * 這是開發用的輔助測試，平常使用這個工具不需要跑它。
 */

const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  let passed = 0, failed = 0;
  const check = (cond, desc) => {
    if (cond) { console.log(`  ✅ ${desc}`); passed++; }
    else { console.log(`  ❌ ${desc}`); failed++; }
  };
  const state = async (id) => await page.locator(`#${id}`).isDisabled();

  await page.goto('http://127.0.0.1:5000/');
  await page.waitForLoadState('load');

  console.log('\n--- 剛打開（限制是預設值）---');
  check(!(await state('btnSearch')), '搜尋：可按');
  check(await state('btnReset'), '還原限制條件：停用（目前就是預設值，按了沒事做）');
  check(await page.locator('#btnSave').count() === 0, '沒有「儲存限制」按鈕了');

  check(await page.locator('#modeDemo').count() === 0,
        '畫面上沒有「示範模式」選項了');
  const modeLabels = await page.locator('.mode span b').allTextContents();
  check(JSON.stringify(modeLabels) === JSON.stringify(['搜尋', '重查']),
        `搜尋方式只剩兩個：${modeLabels.join('、')}`);

  console.log('\n--- 三個開關預設全開 ---');
  for (const name of ['require_availability', 'assume_air_conditioning', 'assume_elevator']) {
    check(await page.locator(`input[name="${name}"]`).isChecked(), `${name}：預設勾選`);
  }

  console.log('\n--- 改動限制條件之後 ---');
  await page.fill('#s_hotel_max_per_night_usd', '150');
  await page.waitForTimeout(100);
  check(!(await state('btnSearch')), '搜尋：仍然可按（不需要先儲存）');
  check(!(await state('btnReset')), '還原限制條件：可按');

  console.log('\n--- 改回預設值 ---');
  await page.fill('#s_hotel_max_per_night_usd', '180.0');
  await page.waitForTimeout(100);
  check(await state('btnReset'), '還原限制條件：恢復停用（180.0 和 180 是同一個數字）');

  console.log('\n--- 還原不可以清掉左邊填好的東西 ---');
  await page.fill('#destination', 'Tokyo Big Sight');
  await page.fill('#city', 'Tokyo');
  await page.fill('#check_in', '2027-03-10');
  await page.fill('#check_out', '2027-03-12');
  await page.fill('#s_hotel_max_per_night_usd', '120');
  await page.waitForTimeout(100);
  await page.click('#btnReset');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);
  check(await page.inputValue('#destination') === 'Tokyo Big Sight', '目的地還在');
  check(await page.inputValue('#city') === 'Tokyo', '城市還在');
  check(await page.inputValue('#check_in') === '2027-03-10', '入住日期還在');
  check(await page.inputValue('#check_out') === '2027-03-12', '退房日期還在');
  check(await page.inputValue('#s_hotel_max_per_night_usd') === '180',
        '限制條件回到預設的 180');

  console.log('\n--- 改了限制直接搜尋，限制會生效並記住 ---');
  // ?demo=1 用內建資料，不連網也不花額度 —— 這是唯一能驗證結果頁渲染的方式
  await page.goto('http://127.0.0.1:5000/?demo=1');
  await page.waitForLoadState('load');
  await page.fill('#s_hotel_max_per_night_usd', '100');
  await page.fill('#check_in', '2027-03-10');
  await page.fill('#check_out', '2027-03-12');
  await page.click('#btnSearch');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);
  const summary = await page.locator('.meta').innerText();
  check(summary.includes('$100'), `摘要顯示套用了 $100 的上限`);
  check((await page.locator('.badge').innerText()).includes('已自訂'),
        '標記為「已自訂」');
  check(!(await state('btnReset')), '還原限制條件：可按（有自訂值可還原）');

  console.log('\n--- 還原之後回到預設 ---');
  await page.click('#btnReset');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);
  check(await page.inputValue('#s_hotel_max_per_night_usd') === '180', '回到 180');
  check(await state('btnReset'), '還原鈕又變成停用');

  console.log('\n--- 目的地沒有下拉，城市有 ---');
  check(await page.getAttribute('#destination', 'list') === null,
        '目的地欄位沒有下拉（直接打字就好）');
  check(await page.getAttribute('#city', 'list') === null,
        '城市欄位改用自訂下拉（JS 已把瀏覽器內建的 datalist 關掉）');
  check(await page.locator('#cityToggle').count() === 1, '城市欄位右邊有 ▾ 展開鈕');
  const cityOptions = await page.locator('#cities option').count();
  check(cityOptions > 50, `城市選單有 ${cityOptions} 個建議（展覽與商務常去的城市）`);
  check(await page.locator('#cities option[value="Sydney"]').count() === 1,
        '雪梨在清單裡');
  check(await page.locator('#cities option[label="已有費率"]').count() >= 4,
        '已填費率的城市有特別標示');
  const names = await page.locator('#cities option').evaluateAll(
    els => els.map(e => e.value));
  const sorted = [...names].sort((a, b) => a.localeCompare(b, 'en'));
  check(JSON.stringify(names) === JSON.stringify(sorted),
        `城市清單由 A 到 Z 排序（${names[0]} … ${names[names.length - 1]}）`);

  console.log('\n--- 清單裡沒有的城市也要能自己打 ---');
  await page.fill('#city', 'Reykjavik');
  check(await page.inputValue('#city') === 'Reykjavik',
        '可以輸入清單上沒有的城市');
  await page.fill('#city', '');

  console.log('\n--- 退房日期不能早於入住隔天 ---');
  await page.goto('http://127.0.0.1:5000/');
  await page.waitForLoadState('load');
  await page.fill('#check_in', '2027-03-01');
  await page.dispatchEvent('#check_in', 'change');
  await page.waitForTimeout(100);
  check(await page.getAttribute('#check_out', 'min') === '2027-03-02',
        '選了 3/01 入住後，退房最早只能選 3/02');

  await page.fill('#check_out', '2027-03-05');
  await page.fill('#check_in', '2027-03-10');
  await page.dispatchEvent('#check_in', 'change');
  await page.waitForTimeout(100);
  check(await page.inputValue('#check_out') === '',
        '把入住改晚之後，已經不合法的退房日期會被清掉而不是留著');
  check(await page.getAttribute('#check_out', 'min') === '2027-03-11',
        '退房下限跟著更新成 3/11');

  console.log('\n--- 每張卡片有兩個連結 ---');
  await page.goto('http://127.0.0.1:5000/?demo=1');
  await page.waitForLoadState('load');
  await page.fill('#check_in', '2027-03-10');
  await page.dispatchEvent('#check_in', 'change');
  await page.fill('#check_out', '2027-03-12');
  await page.click('#btnSearch');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);
  const firstCard = page.locator('.card').first();
  check(await firstCard.locator('a:has-text("官網連結")').count() === 1, '有「官網連結」');
  const compare = firstCard.locator('a:has-text("比價連結")');
  check(await compare.count() === 1, '有「比價連結」');
  check((await compare.getAttribute('href')).startsWith('https://www.google.com/travel/search?q='),
        '比價連結指向 Google Hotels');

  console.log('\n--- 城市下拉：欄位有字的時候也要列出全部（你回報的問題）---');
  await page.fill('#city', 'Sydney');
  await page.click('#cityToggle');
  await page.waitForTimeout(150);
  check(!(await page.locator('#cityList').isHidden()), '按 ▾ 會打開清單');
  const openedAll = await page.locator('#cityList li[data-name]').count();
  check(openedAll > 50,
        `欄位裡已經填著 Sydney，按 ▾ 仍然列出全部 ${openedAll} 個城市`);
  check(await page.locator('#cityList li[data-name="Osaka"]').count() === 1,
        '清單裡找得到跟 Sydney 無關的城市（確認不是只列開頭吻合的）');

  // 打字才過濾
  await page.fill('#city', 'Syd');
  await page.waitForTimeout(150);
  const typed = await page.locator('#cityList li[data-name]').count();
  check(typed > 0 && typed < openedAll, `打字會過濾（剩 ${typed} 筆）`);

  // 點一下就選起來
  await page.locator('#cityList li[data-name]').first().click();
  await page.waitForTimeout(150);
  check(await page.inputValue('#city') === 'Sydney', '點清單項目會填進欄位');
  check(await page.locator('#cityList').isHidden(), '選完清單會收起來');

  // 再按一次 ▾ 應該要能換成別的城市，而不是只剩 Sydney 一筆
  await page.click('#cityToggle');
  await page.waitForTimeout(150);
  check(await page.locator('#cityList li[data-name]').count() === openedAll,
        '選完之後再按 ▾，清單還是完整的（可以直接改選別的城市）');
  await page.keyboard.press('Escape');

  console.log('\n--- 三筆以上改成橫向捲動 ---');
  await page.goto('http://127.0.0.1:5000/?demo=1');
  await page.waitForLoadState('load');
  await page.fill('#check_in', '2027-03-10');
  await page.dispatchEvent('#check_in', 'change');
  await page.fill('#check_out', '2027-03-12');
  await page.click('#btnSearch');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);

  const carousels = page.locator('.carousel');
  check(await carousels.count() >= 2, '三筆以上的區塊都改成橫向捲動');

  // 三筆在寬螢幕上其實放得下 —— 那就不該擺一組按不動的箭頭
  const small = carousels.last();
  check(await small.locator('.card').count() === 3, '最後一區剛好三筆');
  check(await small.locator('.cnav').isHidden(),
        '三筆在這個寬度放得下，箭頭自動收起來');
  const cardW = await small.locator('.card').first()
    .evaluate(el => el.getBoundingClientRect().width);
  check(cardW > 300, `放得下的時候卡片會撐滿整列（寬 ${Math.round(cardW)}px，不是乾乾的 290px）`);

  const track = carousels.first().locator('.track');
  const prev = carousels.first().locator('.prev');
  const next = carousels.first().locator('.next');
  check(!(await carousels.first().locator('.cnav').isHidden()),
        '放不下的區塊才顯示箭頭');
  check(await prev.isDisabled(), '剛載入時「上一批」是停用的（已經在最左邊）');
  check(!(await next.isDisabled()), '「下一批」可以按');

  const scrollBefore = await track.evaluate(el => el.scrollLeft);
  await next.click();
  await page.waitForTimeout(600);
  const scrollAfter = await track.evaluate(el => el.scrollLeft);
  check(scrollAfter > scrollBefore,
        `按「下一批」會往右滑（${scrollBefore} → ${scrollAfter}）`);
  check(!(await prev.isDisabled()), '滑動之後「上一批」變成可按');

  // 捲動是平滑動畫，直接設 scrollLeft 會慢慢滑過去，所以要等它停
  await track.evaluate(el => el.scrollTo({ left: el.scrollWidth,
                                           behavior: 'instant' }));
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.carousel .track');
      return el.scrollLeft + el.clientWidth >= el.scrollWidth - 4;
    }, null, { timeout: 5000 });
  await page.waitForTimeout(100);
  check(await next.isDisabled(), '滑到最右邊時「下一批」變灰');

  console.log('\n--- 重新整理要清空欄位（你回報的問題）---');
  // 必須從乾淨的頁面開始。重新整理一個 POST 出來的結果頁，
  // 瀏覽器會重送那次 POST，伺服器本來就該把同樣的值印回來。
  await page.goto('http://127.0.0.1:5000/');
  await page.waitForLoadState('load');
  await page.fill('#destination', 'Taipei 101');
  await page.fill('#city', 'Taipei');
  await page.fill('#check_in', '2027-03-10');
  await page.fill('#check_out', '2027-03-12');
  await page.waitForTimeout(100);
  check(await page.inputValue('#destination') === 'Taipei 101', '填入值確實生效');

  await page.reload();
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);
  const after = {
    destination: await page.inputValue('#destination'),
    city: await page.inputValue('#city'),
    check_in: await page.inputValue('#check_in'),
    check_out: await page.inputValue('#check_out'),
    mode: await page.locator('input[name="mode"]:checked').getAttribute('value'),
  };
  console.log('    重新整理後：', JSON.stringify(after));
  check(after.destination === '', '目的地已清空');
  check(after.city === '', '城市已清空');
  check(after.check_in === '' && after.check_out === '', '日期已清空');
  check(after.mode === 'cache', '搜尋方式回到預設的「搜尋」');

  console.log('\n--- 搜尋結果頁的欄位應該保留，不能被清掉 ---');
  await page.goto('http://127.0.0.1:5000/?demo=1');
  await page.waitForLoadState('load');
  await page.fill('#destination', 'x');
  await page.fill('#check_in', '2027-03-10');
  await page.fill('#check_out', '2027-03-12');
  await page.click('#btnSearch');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);
  check(await page.inputValue('#check_in') === '2027-03-10', '搜尋後日期仍在欄位裡');
  check((await page.locator('.card').count()) > 0,
        `結果卡片有顯示（${await page.locator('.card').count()} 張）`);

  console.log(`\n${'='.repeat(50)}`);
  console.log(failed === 0 ? `OK —— ${passed} 項全部通過` : `${failed} 項失敗 / ${passed} 項通過`);
  console.log('='.repeat(50));
  await browser.close();
  process.exit(failed === 0 ? 0 : 1);
})();
