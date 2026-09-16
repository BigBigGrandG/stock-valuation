# Repository Safety

本指南定义版本库操作边界，目标是保护用户已有成果并让本次任务的修改可准确识别。

## Baseline

当任务需要修改代码、判断 diff 或交付状态时，先建立与任务相关的 Git 基线，例如：

```powershell
git status --short --branch
git log -5 --oneline --decorate
```

根据需要检查相关 `git diff`、未跟踪文件和当前分支。

不要为了普通阅读任务机械执行 Git 检查；只有当版本库状态会影响修改或结论时才需要。

## Protect Existing Work

必须区分：

- 已提交历史；
- 用户或其他工作的已有 dirty changes；
- 未跟踪文件；
- 本次任务产生的修改。

不得覆盖、删除或冒充不属于本次任务的成果。

`git diff --stat` 不包含未跟踪文件；如果工作区存在 untracked 内容，不得因 diff 为空而声称没有修改。

## Destructive Operations

禁止使用或等价执行：

- `git clean`
- `git reset --hard`
- 破坏性 checkout / restore 覆盖用户修改
- 覆盖式脚手架重建整个项目
- 重新初始化现有 Git 仓库

除非用户对具体不可逆操作给出明确授权，否则应选择可恢复方案。

## Commit / Push / PR

以下操作需要用户明确要求或授权：

- `git commit`
- `git push`
- 创建、更新或合并 Pull Request
- 改写历史

授权只适用于当前请求合理包含的范围，不应扩展为后续任务的永久授权。

## Side Effects

对可能产生外部或不可逆副作用的操作，先确认当前状态，避免盲目重放非幂等动作。

如果一次操作已经部分成功，应从实际状态继续，而不是假设失败后完整重做。

## Delivery

交付时简要说明：

- 实际修改文件；
- 与本次任务无关但仍存在的 dirty / untracked 内容（如果相关）；
- 是否创建 commit / push / PR；
- 尚未处理的版本库风险。
