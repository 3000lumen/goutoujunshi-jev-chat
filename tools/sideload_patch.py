#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 Sideloadly / 免费 Apple ID 侧载修改 狗头军师 iOS 的 Shared/Store.swift。

修复两类问题：
  1. 钥匙串 -34018 (errSecMissingEntitlement)：源码把 kSecAttrAccessGroup 设成了
     "com.xxx" 这种没有 Team 前缀的组，免费签名里不存在该组，秒失败。
     → 去掉 access group，用签名自带默认组；再不行就回退到 UserDefaults。
  2. App Group 不可用：containerURL(forSecurityApplicationGroupIdentifier:) 返回 nil
     时原本直接抛错、App 打不开。→ 回退到 App 自己的沙盒目录。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "integrations" / "jev_ios" / "Shared" / "Store.swift"

REPLACEMENTS = [
    # 1. App Group 缺失时不再抛错
    (
        """        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: Self.group),
              let defaults = UserDefaults(suiteName: Self.group) else {
            throw GoutouError.invalid("共享配置未连接：请在 Xcode 为 App 与键盘配置相同 App Group 和开发者 Team")
        }
        self.container = container
        self.defaults = defaults""",
        """        if let shared = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: Self.group),
           let sharedDefaults = UserDefaults(suiteName: Self.group) {
            self.container = shared
            self.defaults = sharedDefaults
        } else {
            let local = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            try? FileManager.default.createDirectory(at: local, withIntermediateDirectories: true)
            self.container = local
            self.defaults = .standard
        }""",
    ),
    # 2. 本地兜底存储
    (
        """    static let services = ["deepseek", "openrouter", "jev"]""",
        """    static let services = ["deepseek", "openrouter", "jev"]
    private static let fallbackKey = "goutou.secret.fallback"
    private static var fallbackStore: [String: String] {
        get { (UserDefaults.standard.dictionary(forKey: fallbackKey) as? [String: String]) ?? [:] }
        set { UserDefaults.standard.set(newValue, forKey: fallbackKey) }
    }
    private static func fallbackRead(_ name: String) -> String { fallbackStore[name] ?? "" }
    private static func fallbackWrite(_ name: String, _ value: String) { var all = fallbackStore; all[name] = value; fallbackStore = all }
    private static func fallbackDelete(_ name: String) { var all = fallbackStore; all.removeValue(forKey: name); fallbackStore = all }""",
    ),
    # 3. 不再指定 access group
    (
        """        guard services.contains(name), let group = Bundle.main.object(forInfoDictionaryKey: "GoutouKeychainGroup") as? String,
              !group.contains("$("), !group.isEmpty else { throw GoutouError.invalid("共享钥匙串配置未完成，请检查两个 target 的 Keychain Sharing") }
        return [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "ai.goutoujunshi.ios." + name,
                kSecAttrAccount as String: "default", kSecAttrAccessGroup as String: group]""",
        """        guard services.contains(name) else { throw GoutouError.invalid("密钥名称无效") }
        return [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "ai.goutoujunshi.ios." + name,
                kSecAttrAccount as String: "default"]""",
    ),
    # 4. 读取：失败时回退
    (
        """        if status == errSecItemNotFound { return "" }
        guard status == errSecSuccess, let data = item as? Data, let value = String(data: data, encoding: .utf8) else {
            throw GoutouError.invalid("钥匙串读取失败（\\(status)），请检查共享权限")
        }
        return value""",
        """        if status == errSecItemNotFound { return fallbackRead(name) }
        guard status == errSecSuccess, let data = item as? Data, let value = String(data: data, encoding: .utf8) else {
            return fallbackRead(name)
        }
        return value""",
    ),
    # 5. 写入：先落本地，钥匙串失败不报错
    (
        """        let query = try query(name)
        let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes, uniquingKeysWith: { _, new in new }) as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw GoutouError.invalid("密钥保存失败（\\(status)），请检查共享钥匙串签名") }""",
        """        fallbackWrite(name, value)
        let query = try query(name)
        let attributes: [String: Any] = [kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes, uniquingKeysWith: { _, new in new }) as CFDictionary, nil)
        }
        if status != errSecSuccess { /* 钥匙串不可用，已写入本地兜底存储 */ }""",
    ),
    # 6. 删除：同样放行
    (
        """        let status = SecItemDelete(try query(name) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw GoutouError.invalid("无法删除密钥（\\(status)）") }""",
        """        fallbackDelete(name)
        let status = SecItemDelete(try query(name) as CFDictionary)
        if status != errSecSuccess && status != errSecItemNotFound { /* 忽略 */ }""",
    ),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if "goutou.secret.fallback" in text:
        print("ALREADY PATCHED, skip")
        return 0
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        n = text.count(old)
        if n != 1:
            print("PATCH FAIL: rule %d matched %d times" % (i, n))
            return 1
        text = text.replace(old, new)
    TARGET.write_text(text, encoding="utf-8")
    print("PATCH OK -> %s (%d chars)" % (TARGET, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
