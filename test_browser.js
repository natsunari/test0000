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
  check(await state('btnSave'), '儲存限制：停用');
  check(await state('btnReset'), '還原預設：停用');

  console.log('\n--- 改動限制之後（還沒儲存）---');
  await page.fill('#s_hotel_max_per_night_usd', '150');
  await page.waitForTimeout(100);
  check(await state('btnSearch'), '搜尋：停用（避免用舊限制跑出結果）');
  check(!(await state('btnSave')), '儲存限制：可按');
  check(!(await state('btnReset')), '還原預設：可按');
  check(await page.locator('#dirtyHint').isVisible(), '顯示「請先儲存或還原」提示');

  console.log('\n--- 把值改回原本的 ---');
  await page.fill('#s_hotel_max_per_night_usd', '180.0');
  await page.waitForTimeout(100);
  check(!(await state('btnSearch')), '搜尋：恢復可按');
  check(await state('btnSave'), '儲存限制：恢復停用');
  check(!(await page.locator('#dirtyHint').isVisible()), '提示消失');

  console.log('\n--- 切換開關也算改動 ---');
  await page.locator('input[name="assume_air_conditioning"]').uncheck();
  await page.waitForTimeout(100);
  check(await state('btnSearch'), '勾選框改動也會停用搜尋');
  await page.locator('input[name="assume_air_conditioning"]').check();
  await page.waitForTimeout(100);
  check(!(await state('btnSearch')), '改回來就恢復');

  console.log('\n--- 重新整理要清空欄位（你回報的問題）---');
  await page.fill('#destination', 'Taipei 101');
  await page.fill('#city', 'Taipei');
  await page.fill('#check_in', '2027-03-10');
  await page.fill('#check_out', '2027-03-12');
  await page.click('label:has(#modeDemo)');
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
    demo: await page.locator('#modeDemo').isChecked(),
  };
  console.log('    重新整理後：', JSON.stringify(after));
  check(after.destination === '', '目的地已清空');
  check(after.city === '', '城市已清空');
  check(after.check_in === '' && after.check_out === '', '日期已清空');
  check(after.demo === false, '搜尋方式回到預設的「一般搜尋」');

  console.log('\n--- 搜尋結果頁的欄位應該保留，不能被清掉 ---');
  await page.fill('#destination', 'x');
  await page.click('label:has(#modeDemo)');
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
