/* 站点各页共用的串：导航、页脚、复制按钮。
 *
 * 只放确实每页都有的。像 title、lead 这种每页含义不同的，留在各自页面里，
 * 就近改比集中管更不容易出错。
 *
 * 页面自己的表在 window.MIRROR_I18N，键相同时以页面的为准。
 */
window.MIRROR_I18N_COMMON = {
  'zh-tw': {
    brand: 'distfiles.gentoozh.org',
    navSetup: '設定', navPkgs: '套件列表', navFiles: '檔案',
    fSrc: '原始碼', fKey: '簽章公鑰', fDesign: '設計語言', fCommunity: 'Gentoo 中文社群',
    fCommunityUrl: 'https://gentoozh.org/zh-tw/',
    skip: '跳到正文',
    copy: '複製'
  },
  'en': {
    brand: 'distfiles.gentoozh.org',
    navSetup: 'Setup', navPkgs: 'Packages', navFiles: 'Files',
    fSrc: 'Source', fKey: 'Signing key', fDesign: 'Design', fCommunity: 'Gentoo Chinese Community',
    fCommunityUrl: 'https://gentoozh.org/en/',
    skip: 'Skip to content',
    copy: 'Copy'
  }
};
