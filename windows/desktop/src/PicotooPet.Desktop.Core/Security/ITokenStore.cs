namespace PicotooPet.Desktop.Core.Security;

/// <summary>设备令牌安全存储抽象。</summary>
public interface ITokenStore
{
    string? Read();
    void Save(string token);
    void Delete();
}
