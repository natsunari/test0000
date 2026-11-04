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
  check(JSON.stringify(modeLabels) === JSON.stringify(['重查', '搜尋']),
        `搜尋方式兩個，重查在前：${modeLabels.join('、')}`);
  const modeHeading = await page.locator('label:has-text("搜尋方式")').first().textContent();
  check(modeHeading.includes('二選一'), `標題寫「二選一」：${modeHeading.trim()}`);
  check(await page.locator('[name="taxi_max_per_day_usd"]').count() === 0,
        '設定面板上沒有「每日交通上限」欄位了');

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

  console.log('\n--- 卡片往下排，每頁 16 張 ---');
  await page.goto('http://127.0.0.1:5000/?demo=1');
  await page.waitForLoadState('load');
  await page.fill('#check_in', '2027-03-10');
  await page.dispatchEvent('#check_in', 'change');
  await page.fill('#check_out', '2027-03-12');
  await page.click('#btnSearch');
  await page.waitForLoadState('load');
  await page.waitForTimeout(300);

  check(await page.locator('.carousel').count() === 0, '沒有橫向輪播了');
  const paged = page.locator('.paged');
  check(await paged.count() >= 2, '每一區都用分頁容器包起來');

  // 每一區各自算自己的頁數
  const perSection = await paged.evaluateAll(els => els.map(e => ({
    total: e.querySelectorAll('.grid > .card').length,
    visible: Array.from(e.querySelectorAll('.grid > .card'))
      .filter(c => !c.hidden).length,
    hasPager: !!e.querySelector('.pager'),
    pageButtons: e.querySelectorAll('.nums button').length,
  })));
  console.log('    各區：', JSON.stringify(perSection));

  const big = perSection.find(x => x.total > 16);
  const small = perSection.find(x => x.total > 0 && x.total <= 16);

  check(big && big.hasPager, `超過 16 筆的區塊有分頁列（${big && big.total} 筆）`);
  check(big && big.pageButtons === Math.ceil(big.total / 16),
        `${big && big.total} 筆分成 ${big && big.pageButtons} 頁`);
  check(big && big.visible === 16, `第一頁剛好顯示 16 張（實際 ${big && big.visible}）`);

  check(small && !small.hasPager,
        `不到 16 筆的區塊沒有分頁列（${small && small.total} 筆）`);
  check(small && small.visible === small.total,
        '不分頁的區塊所有卡片都看得到');

  // 換頁
  const pager = page.locator('.paged:has(.pager)').first();
  check(await pager.locator('.pprev').isDisabled(), '第一頁時「上一頁」停用');
  check(!(await pager.locator('.pnext').isDisabled()), '第一頁時「下一頁」可按');
  check(await pager.locator('.nums button').first().evaluate(
          b => b.classList.contains('on')),
        '第 1 頁的按鈕是選中狀態');

  await pager.locator('.pnext').click();
  await page.waitForTimeout(400);
  const page2 = await pager.evaluate(e => ({
    visible: Array.from(e.querySelectorAll('.grid > .card'))
      .filter(c => !c.hidden).length,
    total: e.querySelectorAll('.grid > .card').length,
    onIndex: Array.from(e.querySelectorAll('.nums button'))
      .findIndex(b => b.classList.contains('on')),
  }));
  check(page2.visible === page2.total - 16,
        `第二頁顯示剩下的 ${page2.visible} 張`);
  check(page2.onIndex === 1, '第 2 頁的按鈕變成選中狀態');
  check(await pager.locator('.pnext').isDisabled(), '最後一頁時「下一頁」停用');
  check(!(await pager.locator('.pprev').isDisabled()), '最後一頁時「上一頁」可按');

  // 直接點頁碼
  await pager.locator('.nums button').first().click();
  await page.waitForTimeout(400);
  check(await pager.locator('.pprev').isDisabled(), '點頁碼 1 回到第一頁');

  console.log('\n--- 車資標籤要顯示單趟，不是每日（你回報的問題）---');
  // 上限設的是單趟，標籤卻寫「每日」（＝單趟×2），看起來像超標沒被擋
  const fareChip = page.locator('.chip:has-text("🚕")').first();
  if (await fareChip.count()) {
    const text = await fareChip.textContent();
    check(text.includes('單趟'), `車資標籤寫「單趟」：${text.trim()}`);
    check(!text.includes('每日'), '車資標籤不再寫「每日」');
    const title = await fareChip.getAttribute('title');
    check(title && title.includes('來回'), `來回金額放在 title：${title}`);
  } else {
    check(true, '這批結果都是走路可達，沒有車資標籤可驗');
  }

  console.log('\n--- 重新整理結果頁，左邊要清空、右邊要留著（你回報的問題）---');
  // 重新整理 POST 出來的結果頁時，瀏覽器會重送那次 POST，伺服器把同樣的
  // 目的地和日期再印一次。以前 form.reset() 回到的就是那些值，等於沒清。
  await page.goto('http://127.0.0.1:5000/?demo=1');
  await page.waitForLoadState('load');
  await page.fill('#destination', 'Tokyo Big Sight');
  await page.fill('#city', 'Tokyo');
  await page.fill('#check_in', '2027-03-10');
  await page.dispatchEvent('#check_in', 'change');
  await page.fill('#check_out', '2027-03-12');
  await page.fill('#s_hotel_max_per_night_usd', '250');
  await page.click('#btnSearch');
  await page.waitForLoadState('load');
  await page.waitForTimeout(200);
  check(await page.inputValue('#destination') === 'Tokyo Big Sight',
        '剛搜尋完，左邊的欄位還留著（這時候不該清）');

  await page.reload();
  await page.waitForLoadState('load');
  await page.waitForTimeout(400);
  const reloaded = {
    destination: await page.inputValue('#destination'),
    city: await page.inputValue('#city'),
    check_in: await page.inputValue('#check_in'),
    ceiling: await page.inputValue('#s_hotel_max_per_night_usd'),
    results: await page.locator('.card').count(),
  };
  console.log('    重新整理結果頁後：', JSON.stringify(reloaded));
  check(reloaded.destination === '' && reloaded.city === ''
        && reloaded.check_in === '',
        '重新整理後左邊的目的地、城市、日期都清空了');
  check(reloaded.ceiling === '250',
        `右邊的限制條件留著（住宿上限仍是 ${reloaded.ceiling}）`);
  check(reloaded.results > 0, '搜尋結果還在，不會因為清欄位就消失');

  console.log('\n--- 重新整理空白頁也要清空 ---');
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
