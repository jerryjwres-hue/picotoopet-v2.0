using System.Runtime.CompilerServices;

// 仅向仓库内正式 smoke tests 暴露内部旁白实现，生产权限边界不变。
[assembly: InternalsVisibleTo("PicotooPet.Desktop.Core.SmokeTests")]
