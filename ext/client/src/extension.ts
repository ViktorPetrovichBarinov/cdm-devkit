import * as path from "path";
import * as crypto from "crypto";
import * as fs from "fs/promises";
import { constants as fsConstants } from "fs";
import { spawn } from "child_process";
import * as vscode from "vscode";
import { PythonExtension } from "@vscode/python-extension";
import { LanguageClient, LanguageClientOptions, ServerOptions, Trace } from "vscode-languageclient/node";

let client: LanguageClient;
let extensionOutputChannel: vscode.OutputChannel;

async function fileExists(filePath: string): Promise<boolean> {
    try {
        await fs.access(filePath, fsConstants.F_OK);
        return true;
    } catch {
        return false;
    }
}

function runProcess(
    command: string,
    args: string[],
    options: { cwd?: string; env?: NodeJS.ProcessEnv } = {}
): Promise<void> {
    return new Promise((resolve, reject) => {
        extensionOutputChannel?.appendLine(`$ ${command} ${args.join(" ")}`);

        const child = spawn(command, args, {
            cwd: options.cwd,
            env: options.env,
        });

        child.stdout.on("data", (buf) => extensionOutputChannel?.append(buf.toString()));
        child.stderr.on("data", (buf) => extensionOutputChannel?.append(buf.toString()));
        child.on("error", reject);
        child.on("close", (code) => {
            if (code === 0) {
                resolve();
            } else {
                reject(new Error(`Command failed with exit code ${code}: ${command} ${args.join(" ")}`));
            }
        });
    });
}

async function resolvePythonCommand(resource?: vscode.Uri): Promise<string> {
    const config = vscode.workspace.getConfiguration("cdm", resource);
    const configuredPythonPath = config.get<string>("pythonPath");
    if (configuredPythonPath && configuredPythonPath.trim().length > 0) {
        return configuredPythonPath.trim();
    }

    try {
        const pythonApi = await PythonExtension.api();
        await pythonApi.ready;

        const envPath = pythonApi.environments.getActiveEnvironmentPath(resource);
        const resolved = await pythonApi.environments.resolveEnvironment(envPath);

        const interpreterPath = resolved?.executable?.uri?.fsPath;
        if (interpreterPath && interpreterPath.length > 0) {
            return interpreterPath;
        }

        if (envPath?.path && envPath.path.length > 0) {
            return envPath.path;
        }
    } catch (err) {
        extensionOutputChannel?.appendLine(
            `Failed to resolve Python interpreter from Python extension: ${String(err)}`
        );
    }

    return process.platform === "win32" ? "python" : "python3";
}

function getVenvPythonPath(venvDir: string): string {
    return process.platform === "win32"
        ? path.join(venvDir, "Scripts", "python.exe")
        : path.join(venvDir, "bin", "python3");
}

async function sha256File(filePath: string): Promise<string> {
    const buf = await fs.readFile(filePath);
    return crypto.createHash("sha256").update(buf).digest("hex");
}

async function ensurePythonEnvironment(
    context: vscode.ExtensionContext,
    bootstrapPython: string,
    requirementsPath: string,
    resource?: vscode.Uri
): Promise<string> {
    const config = vscode.workspace.getConfiguration("cdm", resource);
    const autoInstall = config.get<boolean>("autoInstall", true);
    if (!autoInstall) {
        return bootstrapPython;
    }

    const storageDir = context.globalStorageUri.fsPath;
    await fs.mkdir(storageDir, { recursive: true });

    const venvDir = path.join(storageDir, "py");
    const venvPython = getVenvPythonPath(venvDir);

    const requirementsHash = await sha256File(requirementsPath);
    const storedHash = context.globalState.get<string>("cdm.requirementsHash");

    const needsVenv = !(await fileExists(venvPython));
    const needsInstall = needsVenv || storedHash !== requirementsHash;

    if (needsInstall) {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: "CDM16 LSP: preparing Python environment",
                cancellable: false,
            },
            async () => {
                if (needsVenv) {
                    extensionOutputChannel.appendLine(`Creating venv at ${venvDir}`);
                    await runProcess(bootstrapPython, ["-m", "venv", venvDir]);
                }

                extensionOutputChannel.appendLine("Installing Python dependencies...");
                await runProcess(venvPython, ["-m", "pip", "install", "--upgrade", "pip"]);
                await runProcess(venvPython, ["-m", "pip", "install", "-r", requirementsPath]);

                await context.globalState.update("cdm.requirementsHash", requirementsHash);
            }
        );
    }

    return venvPython;
}

export async function activate(context: vscode.ExtensionContext) {
    extensionOutputChannel = vscode.window.createOutputChannel("CDM16 Extension");
    extensionOutputChannel.show(true);
    extensionOutputChannel.appendLine("Output channel working well!");

    // relative path to python server from thin file
    const serverPath = context.asAbsolutePath(
        path.join("..", "server", "src", "server.py") 
    );
    extensionOutputChannel.appendLine(`Path to the server ${serverPath}`)

    const workspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri;
    const bootstrapPython = await resolvePythonCommand(workspaceUri);
    extensionOutputChannel.appendLine(`Bootstrap Python interpreter: ${bootstrapPython}`);

    const requirementsPath = context.asAbsolutePath(path.join("..", "requirements.txt"));
    const pythonCommand = await ensurePythonEnvironment(context, bootstrapPython, requirementsPath, workspaceUri);
    extensionOutputChannel.appendLine(`Server Python interpreter: ${pythonCommand}`);

    // launch python server
    const serverOptions: ServerOptions = {
        command: pythonCommand,
        args: [serverPath],
        options: { cwd: path.dirname(serverPath) },
    };

    // client options
    const config = vscode.workspace.getConfiguration('cdm');
    const dialect = config.get('dialect', 'cdm16');
    extensionOutputChannel.appendLine(`CDM dialect from config: ${dialect}`);

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "*" }],
        outputChannel: vscode.window.createOutputChannel("CDM16 LSP"),
        initializationOptions: {
            dialect: dialect
        }
    };

    // Create and launch client
    client = new LanguageClient(
        "cdm16-lsp",                    // client-id
        "CDM16 Language Server",        // log's name
        serverOptions,
        clientOptions
    );
    client.setTrace(Trace.Verbose);

    // Запускаем клиента
    await client.start();
    extensionOutputChannel.appendLine("CDM16 LSP client started!");

    context.subscriptions.push(client);
}

export async function deactivate(): Promise<void> {
    if (client) {
        await client.stop();
    }
}
